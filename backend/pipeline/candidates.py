"""Multi-source watchlist candidate selection.

The watchlist used to come exclusively from Reddit hot-post buzz. That made
report quality hostage to one noisy source: on quiet Reddit days (or when
Reddit blocks server IPs and the RSS fallback loses engagement data) the
pipeline researched junk tickers and produced nothing of substance.

Candidates now come from four independent source classes, merged and scored:

- reddit:   engagement-weighted buzz (existing behaviour)
- movers:   biggest daily % moves across a liquid, optionable core universe
- earnings: names reporting within the next few days (Finnhub or DB calendar)
- catalyst: tickers attached to recent catalyst-wire items and market news

Each class gets guaranteed watchlist slots so a dead source never blanks the
list, and multi-source tickers rank first.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from config import settings
from pipeline.prices import close_pair, fetch_daily_closes

logger = logging.getLogger(__name__)

# Liquid single names with active options markets. Used for the movers screen
# (one batched download) — Reddit/news/earnings cover discovery outside it.
CORE_LIQUID_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD",
    "INTC", "MU", "TSM", "QCOM", "ARM", "SMCI", "PLTR", "CRM", "ORCL", "ADBE",
    "NFLX", "DIS", "UBER", "ABNB", "COIN", "HOOD", "MSTR", "PYPL", "SHOP",
    "SNOW", "CRWD", "PANW", "NET", "DDOG", "MDB", "JPM", "BAC", "GS", "MS",
    "WFC", "C", "V", "MA", "AXP", "XOM", "CVX", "OXY", "COP", "SLB", "BA",
    "CAT", "DE", "GE", "F", "GM", "RIVN", "LCID", "NIO", "BABA", "JD", "PDD",
    "NKE", "SBUX", "MCD", "WMT", "COST", "TGT", "HD", "LOW", "PFE", "MRNA",
    "JNJ", "LLY", "UNH", "ABBV", "BMY", "GILD", "AMGN", "CVS", "T", "VZ",
    "TMUS", "SOFI", "AFRM", "UPST", "GME", "AMC", "RIOT", "MARA", "CLSK",
    "DKNG", "RBLX", "SNAP", "PINS", "ROKU", "ENPH", "FSLR", "CELH", "LULU",
]

_MIN_MOVER_PCT = 1.5


@dataclass
class CandidateSet:
    tickers: list[str]
    sources_by_ticker: dict[str, list[str]]
    details: dict[str, Any] = field(default_factory=dict)


def _pct_moves_from_history(as_of: date | None) -> dict[str, float]:
    """Batched close-to-close % moves for the core list. When `as_of` is set
    (backfill), the move is computed for that session instead of the latest."""
    end = (as_of + timedelta(days=1)) if as_of else date.today() + timedelta(days=1)
    start = end - timedelta(days=21)
    all_series = fetch_daily_closes(CORE_LIQUID_TICKERS, start, end)
    moves: dict[str, float] = {}
    for ticker, series in all_series.items():
        pair = close_pair(series, as_of)
        if pair is None:
            continue
        last, prev = pair
        if prev > 0:
            moves[ticker] = round((last - prev) / prev * 100, 2)
    return moves


async def fetch_day_movers(
    as_of: date | None = None,
    top_n: int = 8,
) -> list[tuple[str, float]]:
    """Top absolute % movers, biggest move first. Empty list on failure."""
    try:
        moves = await asyncio.to_thread(_pct_moves_from_history, as_of)
    except Exception as exc:
        logger.warning("Movers screen failed: %s", exc)
        return []
    ranked = sorted(moves.items(), key=lambda kv: -abs(kv[1]))
    return [(t, pct) for t, pct in ranked if abs(pct) >= _MIN_MOVER_PCT][:top_n]


async def fetch_earnings_candidates(
    as_of: date | None = None,
    days: int = 3,
    limit: int = 8,
) -> list[tuple[str, str]]:
    """(ticker, earnings date) for names reporting soon. Finnhub when keyed,
    else the calendar_events table populated by the worker."""
    start = as_of or date.today()
    end = start + timedelta(days=days)

    from pipeline.finnhub import finnhub_client

    if finnhub_client.enabled:
        try:
            events = await finnhub_client.fetch_earnings_calendar(
                start.isoformat(), end.isoformat()
            )
            events = [e for e in events if e.ticker and e.ticker.isalpha()]
            # Revenue estimate as a liquidity/size proxy — the raw calendar is
            # dominated by micro caps with no options market.
            events.sort(key=lambda e: -(e.revenue_estimate or 0))
            return [(e.ticker.upper(), e.date) for e in events[:limit]]
        except Exception as exc:
            logger.warning("Finnhub earnings calendar failed: %s", exc)

    try:
        from database import list_calendar_events

        calendar = await list_calendar_events(days=days)
        return [
            (e.ticker.upper(), e.event_date.isoformat())
            for e in calendar
            if e.ticker and e.event_type == "earnings"
        ][:limit]
    except Exception as exc:
        logger.warning("Calendar events lookup failed: %s", exc)
        return []


def catalyst_ticker_counts(overnight_catalysts: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for cat in overnight_catalysts or []:
        weight = 1 + int(cat.get("impact_score") or 0) // 4
        for t in {str(cat.get("primary_ticker") or "").upper(), *(
            str(x).upper() for x in cat.get("related_tickers") or []
        )}:
            if t:
                counts[t] = counts.get(t, 0) + weight
    return counts


def merge_candidates(
    *,
    buzz_scores: dict[str, float],
    movers: list[tuple[str, float]],
    earnings: list[tuple[str, str]],
    catalyst_counts: dict[str, int],
    universe: set[str] | None,
    limit: int | None = None,
) -> CandidateSet:
    limit = limit or settings.max_tickers

    def in_universe(t: str) -> bool:
        return universe is None or t in universe

    scores: dict[str, float] = {}
    sources: dict[str, set[str]] = {}
    notes: dict[str, dict[str, Any]] = {}

    def add(ticker: str, source: str, points: float, **note: Any) -> None:
        t = ticker.upper()
        if not in_universe(t):
            return
        scores[t] = scores.get(t, 0.0) + points
        sources.setdefault(t, set()).add(source)
        notes.setdefault(t, {}).update(note)

    ranked_buzz = sorted(buzz_scores.items(), key=lambda kv: -kv[1])
    for rank, (ticker, buzz) in enumerate(ranked_buzz[:20]):
        add(ticker, "reddit", max(10 - rank, 1), buzz=round(buzz, 1))

    for ticker, pct in movers:
        add(ticker, "movers", min(abs(pct), 10.0), day_move_pct=pct)

    for ticker, when in earnings:
        add(ticker, "earnings", 5.0, earnings_date=when)

    for ticker, count in sorted(catalyst_counts.items(), key=lambda kv: -kv[1])[:10]:
        add(ticker, "catalyst", min(2.0 * count, 8.0), catalyst_hits=count)

    # Corroboration across source classes is the strongest selection signal
    for ticker, src in sources.items():
        if len(src) > 1:
            scores[ticker] += 4.0 * (len(src) - 1)

    ordered = sorted(scores, key=lambda t: -scores[t])

    # Guaranteed slots per source class so one dead feed can't blank the list
    guaranteed: list[str] = []

    def reserve(source: str, count: int) -> None:
        for ticker in ordered:
            if count <= 0:
                break
            if source in sources[ticker] and ticker not in guaranteed:
                guaranteed.append(ticker)
                count -= 1

    reserve("reddit", 4)
    reserve("movers", 3)
    reserve("earnings", 2)
    reserve("catalyst", 2)

    final = list(guaranteed[:limit])
    for ticker in ordered:
        if len(final) >= limit:
            break
        if ticker not in final:
            final.append(ticker)

    return CandidateSet(
        tickers=final,
        sources_by_ticker={t: sorted(sources.get(t, set())) for t in final},
        details={
            t: {"score": round(scores.get(t, 0.0), 1), **notes.get(t, {})} for t in final
        },
    )


async def gather_candidates(
    *,
    buzz_scores: dict[str, float],
    overnight_catalysts: list[dict[str, Any]],
    universe: set[str] | None,
    as_of: date | None = None,
    limit: int | None = None,
) -> CandidateSet:
    movers, earnings = await asyncio.gather(
        fetch_day_movers(as_of=as_of),
        fetch_earnings_candidates(as_of=as_of),
    )
    return merge_candidates(
        buzz_scores=buzz_scores,
        movers=movers,
        earnings=earnings,
        catalyst_counts=catalyst_ticker_counts(overnight_catalysts),
        universe=universe,
        limit=limit,
    )
