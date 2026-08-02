"""Grade recorded bet decisions against final scores and closing lines.

Runs periodically from the worker: finds open BET rows whose game should be
finished, pulls final scores from The Odds API scores endpoint, settles
won/lost/push, and computes closing-line value (CLV) — whether the price we
bet beat the market's final consensus, the strongest known predictor of
long-run betting skill.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from database import (
    get_sports_odds_history,
    list_sports_bet_decisions,
    settle_sports_bet_decision,
)
from pipeline.odds import fetch_event_scores
from pipeline.odds_math import american_to_decimal, american_to_implied_prob
from time_utils import parse_datetime, utc_now

logger = logging.getLogger(__name__)

# Longest plausible game duration; only grade after commence + this buffer.
GAME_OVER_BUFFER_HOURS = 4.0
# Scores endpoint covers at most 3 days back; older ungraded rows are voided.
SCORES_LOOKBACK_DAYS = 3
# Snapshot rows written during the same board build differ by milliseconds;
# treat rows within this window of the latest pregame snapshot as one batch.
CLOSING_BATCH_WINDOW_MINUTES = 10.0


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        parsed = parse_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def grade_outcome(
    *,
    market: str,
    selection: str,
    point: Optional[float],
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
) -> str:
    """Return won | lost | push for a settled game."""
    if market == "h2h":
        if selection == "Draw":
            return "won" if home_score == away_score else "lost"
        if home_score == away_score:
            return "push"
        winner = home_team if home_score > away_score else away_team
        return "won" if selection == winner else "lost"

    if market == "spreads":
        if point is None:
            return "void"
        margin = (home_score - away_score) if selection == home_team else (away_score - home_score)
        adjusted = margin + point
        if adjusted > 0:
            return "won"
        if adjusted < 0:
            return "lost"
        return "push"

    if market == "totals":
        if point is None:
            return "void"
        total = home_score + away_score
        if total == point:
            return "push"
        if selection.lower() == "over":
            return "won" if total > point else "lost"
        if selection.lower() == "under":
            return "won" if total < point else "lost"
        return "void"

    return "void"


async def compute_closing_price(
    event_key: str,
    market: str,
    selection: str,
    point: Optional[float],
    commence: datetime,
) -> Optional[float]:
    """Best cross-book price for the selection in the final pregame snapshot."""
    rows = await get_sports_odds_history(event_key, market, limit=2000)
    pregame: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        ts = _parse_ts(row.get("snapshot_at", ""))
        if ts is not None and ts <= commence:
            pregame.append((ts, row))
    if not pregame:
        return None

    latest = max(ts for ts, _ in pregame)
    window = timedelta(minutes=CLOSING_BATCH_WINDOW_MINUTES)
    batch = [row for ts, row in pregame if latest - ts <= window]

    best: Optional[float] = None
    fallback: Optional[float] = None
    for row in batch:
        for outcome in (row.get("line") or {}).get("outcomes", []):
            if outcome.get("name") != selection:
                continue
            price = float(outcome.get("price", 0))
            outcome_point = outcome.get("point")
            if point is not None and outcome_point is not None:
                if abs(float(outcome_point) - point) <= 0.01:
                    best = price if best is None else max(best, price)
                else:
                    fallback = price if fallback is None else max(fallback, price)
            else:
                best = price if best is None else max(best, price)
    return best if best is not None else fallback


def compute_clv_pct(bet_price: float, closing_price: Optional[float]) -> Optional[float]:
    """Positive when the bet price beat the closing consensus."""
    if closing_price is None:
        return None
    bet_implied = american_to_implied_prob(bet_price)
    close_implied = american_to_implied_prob(closing_price)
    if bet_implied <= 0 or close_implied <= 0:
        return None
    return round((close_implied - bet_implied) * 100.0, 2)


def _match_score_event(
    scores: list[dict[str, Any]],
    home_team: str,
    away_team: str,
) -> Optional[dict[str, Any]]:
    for event in scores:
        if event.get("home_team") == home_team and event.get("away_team") == away_team:
            return event
    return None


def _extract_scores(event: dict[str, Any], home_team: str, away_team: str) -> Optional[tuple[int, int]]:
    entries = event.get("scores") or []
    by_name: dict[str, int] = {}
    for entry in entries:
        try:
            by_name[entry.get("name", "")] = int(float(entry.get("score", "")))
        except (TypeError, ValueError):
            continue
    if home_team in by_name and away_team in by_name:
        return by_name[home_team], by_name[away_team]
    return None


def compute_record_stats(entries: list[Any]) -> dict[str, Any]:
    """Aggregate win/loss record, units P&L, and average CLV.

    Entries can be model instances or dicts with the decision-log fields.
    Units P&L assumes flat settlement at the recorded stake and price."""

    def _get(entry: Any, key: str, default: Any = None) -> Any:
        if isinstance(entry, dict):
            return entry.get(key, default)
        return getattr(entry, key, default)

    counts = {"won": 0, "lost": 0, "push": 0, "void": 0, "open": 0}
    units_pnl = 0.0
    units_staked = 0.0
    clv_values: list[float] = []
    for entry in entries:
        status = _get(entry, "status", "open") or "open"
        counts[status] = counts.get(status, 0) + 1
        stake = float(_get(entry, "stake_units", 0.0) or 0.0)
        price = float(_get(entry, "best_price", 0.0) or 0.0)
        if status == "won":
            units_pnl += stake * (american_to_decimal(price) - 1.0)
            units_staked += stake
        elif status == "lost":
            units_pnl -= stake
            units_staked += stake
        clv = _get(entry, "clv_pct")
        if clv is not None:
            clv_values.append(float(clv))

    settled = counts["won"] + counts["lost"]
    return {
        **counts,
        "settled": settled,
        "hit_rate": round(counts["won"] / settled, 3) if settled else None,
        "units_staked": round(units_staked, 2),
        "units_pnl": round(units_pnl, 2),
        "roi_pct": round(units_pnl / units_staked * 100.0, 1) if units_staked else None,
        "avg_clv_pct": round(sum(clv_values) / len(clv_values), 2) if clv_values else None,
    }


async def grade_open_sports_bets(now: Optional[datetime] = None) -> dict[str, int]:
    """Settle finished games among open BET rows. Returns settlement counts."""
    now = now or utc_now()
    open_bets = await list_sports_bet_decisions(decision="bet", status="open", limit=200)

    due: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    for row in open_bets:
        commence = _parse_ts(row.get("commence_time", ""))
        if commence is None:
            stale.append(row)
            continue
        age_hours = (now - commence).total_seconds() / 3600.0
        if age_hours < GAME_OVER_BUFFER_HOURS:
            continue
        if age_hours > SCORES_LOOKBACK_DAYS * 24.0:
            stale.append(row)
        else:
            due.append(row)

    counts = {"won": 0, "lost": 0, "push": 0, "void": 0}

    for row in stale:
        await settle_sports_bet_decision(row["id"], status="void")
        counts["void"] += 1

    scores_by_sport: dict[str, list[dict[str, Any]]] = {}
    for row in due:
        sport_key = row["sport_key"]
        if sport_key not in scores_by_sport:
            scores_by_sport[sport_key] = await fetch_event_scores(
                sport_key, days_from=SCORES_LOOKBACK_DAYS
            )
        event = _match_score_event(scores_by_sport[sport_key], row["home_team"], row["away_team"])
        if not event or not event.get("completed"):
            continue
        parsed = _extract_scores(event, row["home_team"], row["away_team"])
        if parsed is None:
            continue
        home_score, away_score = parsed

        status = grade_outcome(
            market=row["market"],
            selection=row["selection"],
            point=row["point"],
            home_team=row["home_team"],
            away_team=row["away_team"],
            home_score=home_score,
            away_score=away_score,
        )

        commence = _parse_ts(row["commence_time"])
        closing_price = None
        if commence is not None:
            closing_price = await compute_closing_price(
                row["event_key"], row["market"], row["selection"], row["point"], commence
            )
        clv = compute_clv_pct(float(row["best_price"]), closing_price)

        await settle_sports_bet_decision(
            row["id"],
            status=status,
            home_score=home_score,
            away_score=away_score,
            closing_price=closing_price,
            clv_pct=clv,
        )
        counts[status] = counts.get(status, 0) + 1
        logger.info(
            "Graded %s %s %s: %s (%s-%s, CLV %s)",
            row["matchup"],
            row["market"],
            row["selection"],
            status,
            home_score,
            away_score,
            clv,
        )

    return counts
