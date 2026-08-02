"""Deterministic sports bet decision engine.

Mirrors the equities strategies.py philosophy: turn raw market data into
concrete, sized decisions instead of observations. For every game commencing
within the configured horizon (default 3 days) it:

1. Builds a cross-book consensus fair probability per outcome (vig removed
   per book, averaged across books) for h2h, spreads, and totals markets.
2. Finds the best available price per outcome and computes the probability
   edge and expected value of betting it at that price.
3. Reads line movement (opening snapshot vs current) and matched-news volume
   as confirmation signals.
4. Emits a decision — "bet", "lean", or "pass" — with a confidence score,
   a fractional-Kelly stake in units, an explicit rationale, and a
   sport-aware research checklist to run before firing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from pipeline.odds_math import american_to_decimal, american_to_implied_prob, remove_vig
from time_utils import parse_datetime

DECISION_BET = "bet"
DECISION_LEAN = "lean"
DECISION_PASS = "pass"

MARKET_LABELS = {
    "h2h": "moneyline",
    "spreads": "spread",
    "totals": "total",
}


@dataclass
class OutcomeQuote:
    """One bookmaker's quote for a specific outcome identity."""

    bookmaker: str
    price: float
    fair_probability: float
    point: Optional[float] = None


@dataclass
class BetCandidate:
    market: str
    selection: str
    point: Optional[float]
    best_price: float
    best_bookmaker: str
    consensus_probability: float
    implied_probability: float
    edge_pct: float
    ev_pct: float
    book_count: int


@dataclass
class BetDecision:
    event_key: str
    sport_key: str
    sport_title: str
    home_team: str
    away_team: str
    matchup: str
    commence_time: str
    market: str
    market_label: str
    selection: str
    point: Optional[float]
    best_price: float
    best_bookmaker: str
    consensus_probability: float
    implied_probability: float
    edge_pct: float
    ev_pct: float
    kelly_fraction: float
    stake_units: float
    decision: str
    confidence: float
    rationale: str
    key_factors: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    research_checklist: list[str] = field(default_factory=list)
    line_movement_note: Optional[str] = None
    news_support_count: int = 0


def hours_until(commence_time: str, now: datetime) -> Optional[float]:
    try:
        commence = parse_datetime(commence_time)
    except (TypeError, ValueError):
        return None
    if commence.tzinfo is None:
        commence = commence.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (commence - now).total_seconds() / 3600.0


def within_bet_horizon(
    commence_time: str,
    now: datetime,
    *,
    horizon_days: int,
    allow_live_hours: float = 3.0,
) -> bool:
    """True when the game is upcoming (or just started) and inside the horizon."""
    hours = hours_until(commence_time, now)
    if hours is None:
        return False
    return -allow_live_hours <= hours <= horizon_days * 24.0


def _outcome_identity(name: str, point: Any) -> tuple[str, Optional[float]]:
    parsed: Optional[float] = None
    if point is not None:
        try:
            parsed = float(point)
        except (TypeError, ValueError):
            parsed = None
    return (name, parsed)


def collect_outcome_quotes(
    line_dicts: list[dict[str, Any]],
    market: str,
) -> dict[tuple[str, Optional[float]], list[OutcomeQuote]]:
    """Per-outcome quotes with per-book vig-removed fair probabilities.

    Outcome identity includes the point so spreads/totals only compare
    quotes at the same number.
    """
    quotes: dict[tuple[str, Optional[float]], list[OutcomeQuote]] = defaultdict(list)
    for line in line_dicts:
        if line.get("market") != market:
            continue
        outcomes = [o for o in line.get("outcomes", []) if o.get("name")]
        if len(outcomes) < 2:
            continue
        fair = remove_vig(outcomes)
        for outcome in fair:
            prob = outcome.get("fair_probability")
            if prob is None:
                continue
            identity = _outcome_identity(outcome["name"], outcome.get("point"))
            quotes[identity].append(
                OutcomeQuote(
                    bookmaker=line.get("bookmaker", ""),
                    price=float(outcome.get("price", 0)),
                    fair_probability=float(prob),
                    point=identity[1],
                )
            )
    return quotes


def evaluate_market(
    line_dicts: list[dict[str, Any]],
    market: str,
    *,
    min_books: int = 2,
) -> list[BetCandidate]:
    """Rank outcomes of one market by expected value at the best price."""
    candidates: list[BetCandidate] = []
    for (name, point), outcome_quotes in collect_outcome_quotes(line_dicts, market).items():
        if len(outcome_quotes) < min_books:
            continue
        consensus = sum(q.fair_probability for q in outcome_quotes) / len(outcome_quotes)
        best = max(outcome_quotes, key=lambda q: q.price)
        implied = american_to_implied_prob(best.price)
        if implied <= 0:
            continue
        decimal = american_to_decimal(best.price)
        ev = consensus * (decimal - 1.0) - (1.0 - consensus)
        candidates.append(
            BetCandidate(
                market=market,
                selection=name,
                point=point,
                best_price=best.price,
                best_bookmaker=best.bookmaker,
                consensus_probability=round(consensus, 4),
                implied_probability=round(implied, 4),
                edge_pct=round((consensus - implied) * 100.0, 2),
                ev_pct=round(ev * 100.0, 2),
                book_count=len(outcome_quotes),
            )
        )
    candidates.sort(key=lambda c: -c.ev_pct)
    return candidates


def kelly_fraction(probability: float, american_price: float) -> float:
    """Full Kelly fraction of bankroll for a given win probability and price."""
    b = american_to_decimal(american_price) - 1.0
    if b <= 0:
        return 0.0
    f = (probability * b - (1.0 - probability)) / b
    return max(f, 0.0)


def _movement_favors(selection: str, movement_note: Optional[str]) -> bool:
    """True when the line moved toward (shortened on) the selection.

    Movement notes look like "Chiefs: +120 -> +105"; a falling price for the
    selection means the market is steaming toward it.
    """
    if not movement_note:
        return False
    for part in movement_note.split(";"):
        if selection not in part or "->" not in part:
            continue
        try:
            before_raw, after_raw = part.split(":", 1)[1].split("->")
            before = float(before_raw.strip().replace("+", ""))
            after = float(after_raw.strip().replace("+", ""))
        except (ValueError, IndexError):
            continue
        return american_to_implied_prob(after) > american_to_implied_prob(before)
    return False


RESEARCH_CHECKLIST_BASE = [
    "Confirm starting lineups / scratches within 60 minutes of start",
    "Re-check the line at 2-3 books right before bet placement — edge decays fast",
    "Scan beat-writer feeds for late injury or rotation news the wire may have missed",
    "Compare your number to the closing-line consensus; pass if the edge is gone",
]

SPORT_CHECKLIST_EXTRAS: dict[str, list[str]] = {
    "americanfootball": [
        "Check weather (wind >15mph suppresses totals) and field conditions",
        "Verify QB/OL injury designations on the final report",
    ],
    "basketball": [
        "Check rest spots: back-to-backs and 3-games-in-4-nights fade legs",
        "Confirm star-player load management status",
    ],
    "baseball": [
        "Confirm starting pitchers and bullpen availability from yesterday's usage",
        "Check ballpark and wind direction for totals",
    ],
    "icehockey": [
        "Confirm starting goalies — the single biggest line mover",
        "Check special-teams matchups (PP vs PK) for totals",
    ],
    "soccer": [
        "Check squad rotation risk around congested fixtures / cup ties",
        "Confirm key-player fitness from final pre-match presser",
    ],
}


def build_research_checklist(sport_key: str) -> list[str]:
    prefix = sport_key.split("_", 1)[0] if sport_key else ""
    extras = SPORT_CHECKLIST_EXTRAS.get(prefix, [])
    return extras + RESEARCH_CHECKLIST_BASE


def _format_price(price: float) -> str:
    return f"{price:+.0f}"


def analyze_game(
    *,
    event_key: str,
    sport_key: str,
    sport_title: str,
    home_team: str,
    away_team: str,
    commence_time: str,
    line_dicts: list[dict[str, Any]],
    movement_note: Optional[str] = None,
    news_count: int = 0,
    now: Optional[datetime] = None,
) -> Optional[BetDecision]:
    """Produce the single best decision for a game, or None without pricing data."""
    from config import settings

    now = now or datetime.now(timezone.utc)
    if not within_bet_horizon(
        commence_time, now, horizon_days=settings.sports_bet_horizon_days
    ):
        return None

    candidates: list[BetCandidate] = []
    for market in ("h2h", "spreads", "totals"):
        candidates.extend(evaluate_market(line_dicts, market, min_books=2))
    if not candidates:
        return None

    best = max(candidates, key=lambda c: c.ev_pct)
    movement_confirms = _movement_favors(best.selection, movement_note)

    meets_edge = best.edge_pct >= settings.sports_min_edge_pct
    meets_ev = best.ev_pct >= settings.sports_min_ev_pct
    meets_depth = best.book_count >= settings.sports_min_books_for_decision

    if meets_edge and meets_ev and meets_depth:
        decision = DECISION_BET
    elif best.ev_pct > 0:
        decision = DECISION_LEAN
    else:
        decision = DECISION_PASS

    confidence = min(
        10.0,
        max(best.edge_pct, 0.0) * 1.2
        + min(best.book_count, 8) * 0.5
        + (1.5 if movement_confirms else 0.0)
        + min(news_count, 3) * 0.5,
    )

    full_kelly = kelly_fraction(best.consensus_probability, best.best_price)
    stake = full_kelly * settings.sports_kelly_multiplier * 100.0
    stake = min(stake, settings.sports_max_stake_units)
    if decision != DECISION_BET:
        stake = 0.0
    stake_units = round(stake, 2)

    market_label = MARKET_LABELS.get(best.market, best.market)
    point_str = f" {best.point:+g}" if best.point is not None and best.market == "spreads" else (
        f" {best.point:g}" if best.point is not None else ""
    )
    pick = f"{best.selection}{point_str} {market_label} {_format_price(best.best_price)} @ {best.best_bookmaker}"

    key_factors = [
        f"Consensus fair probability {best.consensus_probability:.1%} vs "
        f"{best.implied_probability:.1%} implied at best price ({best.edge_pct:+.1f} pts edge)",
        f"Expected value {best.ev_pct:+.1f}% per unit staked across {best.book_count} books",
    ]
    if movement_confirms:
        key_factors.append(f"Line movement confirms: {movement_note}")
    elif movement_note:
        key_factors.append(f"Line movement (mixed/against): {movement_note}")
    if news_count:
        key_factors.append(f"{news_count} matched news article(s) — read before firing")

    risks = [
        "Consensus probability is derived from bookmaker prices, not a true model — "
        "correlated book errors inflate apparent edge",
        "Late injury/lineup news can invalidate the number instantly",
    ]
    if best.book_count < settings.sports_min_books_for_decision:
        risks.append(f"Thin market: only {best.book_count} books quoting this outcome")
    if abs(best.best_price) >= 250:
        risks.append("Longshot pricing — higher variance, small edges are less reliable")

    if decision == DECISION_BET:
        rationale = (
            f"BET {pick}: the best available price is meaningfully better than the "
            f"cross-book fair value ({best.ev_pct:+.1f}% EV). Stake {stake_units}u "
            f"(quarter-Kelly, capped)."
        )
    elif decision == DECISION_LEAN:
        rationale = (
            f"LEAN {pick}: positive expected value ({best.ev_pct:+.1f}%) but below the "
            f"bet threshold or too few books — watch for the number to improve."
        )
    else:
        rationale = (
            f"PASS on {away_team} @ {home_team}: no outcome offers positive expected "
            f"value at current prices; the market is efficiently priced."
        )

    return BetDecision(
        event_key=event_key,
        sport_key=sport_key,
        sport_title=sport_title,
        home_team=home_team,
        away_team=away_team,
        matchup=f"{away_team} @ {home_team}",
        commence_time=commence_time,
        market=best.market,
        market_label=market_label,
        selection=best.selection,
        point=best.point,
        best_price=best.best_price,
        best_bookmaker=best.best_bookmaker,
        consensus_probability=best.consensus_probability,
        implied_probability=best.implied_probability,
        edge_pct=best.edge_pct,
        ev_pct=best.ev_pct,
        kelly_fraction=round(full_kelly, 4),
        stake_units=stake_units,
        decision=decision,
        confidence=round(confidence, 1),
        rationale=rationale,
        key_factors=key_factors,
        risks=risks,
        research_checklist=build_research_checklist(sport_key),
        line_movement_note=movement_note,
        news_support_count=news_count,
    )


def _lines_from_raw_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for bookmaker in event.get("bookmakers", []) or []:
        for market in bookmaker.get("markets", []) or []:
            lines.append(
                {
                    "bookmaker": bookmaker.get("title", ""),
                    "market": market.get("key", ""),
                    "outcomes": [
                        {"name": o.get("name"), "price": o.get("price"), "point": o.get("point")}
                        for o in market.get("outcomes", [])
                    ],
                }
            )
    return lines


def analyze_raw_events(
    events: list[dict[str, Any]],
    *,
    news_counts: Optional[dict[str, int]] = None,
    now: Optional[datetime] = None,
) -> list[BetDecision]:
    """Decisions for raw Odds API event dicts (used by the briefing pipeline)."""
    news_counts = news_counts or {}
    now = now or datetime.now(timezone.utc)
    decisions: list[BetDecision] = []
    for event in events:
        sport_key = event.get("sport_key", "")
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        commence = event.get("commence_time", "")
        event_key = event.get("id") or f"{sport_key}|{home}|{away}|{commence}"
        decision = analyze_game(
            event_key=event_key,
            sport_key=sport_key,
            sport_title=event.get("sport_title", sport_key),
            home_team=home,
            away_team=away,
            commence_time=commence,
            line_dicts=_lines_from_raw_event(event),
            news_count=news_counts.get(event_key, 0),
            now=now,
        )
        if decision:
            decisions.append(decision)
    decisions.sort(key=lambda d: ({"bet": 0, "lean": 1, "pass": 2}[d.decision], -d.ev_pct))
    return decisions


def decision_to_dict(decision: BetDecision) -> dict[str, Any]:
    return {
        "event_key": decision.event_key,
        "sport_key": decision.sport_key,
        "sport_title": decision.sport_title,
        "home_team": decision.home_team,
        "away_team": decision.away_team,
        "matchup": decision.matchup,
        "commence_time": decision.commence_time,
        "market": decision.market,
        "market_label": decision.market_label,
        "selection": decision.selection,
        "point": decision.point,
        "best_price": decision.best_price,
        "best_bookmaker": decision.best_bookmaker,
        "consensus_probability": decision.consensus_probability,
        "implied_probability": decision.implied_probability,
        "edge_pct": decision.edge_pct,
        "ev_pct": decision.ev_pct,
        "kelly_fraction": decision.kelly_fraction,
        "stake_units": decision.stake_units,
        "decision": decision.decision,
        "confidence": decision.confidence,
        "rationale": decision.rationale,
        "key_factors": decision.key_factors,
        "risks": decision.risks,
        "research_checklist": decision.research_checklist,
        "line_movement_note": decision.line_movement_note,
        "news_support_count": decision.news_support_count,
    }
