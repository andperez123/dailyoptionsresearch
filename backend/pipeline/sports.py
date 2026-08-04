from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from database import get_sports_odds_history, save_sports_odds_snapshot
from models import (
    SportsBetDecision,
    SportsBoardResponse,
    SportsGameCard,
    SportsNewsContext,
    SportsOddsLine,
)
from pipeline.odds import fetch_raw_odds_events, get_last_odds_quota
from pipeline.odds_math import best_h2h_line, best_market_line, line_movement_delta
from pipeline.odds_relevance import rank_events
from pipeline.sports_news import attach_news_to_events, collect_sports_news, feed_keys_for_sport
from pipeline.sports_strategies import (
    DECISION_BET,
    analyze_game,
    build_scan_review,
    decision_to_dict,
    event_key_for,
    finalize_decisions,
    rank_setups,
    within_bet_horizon,
)
from time_utils import parse_datetime, utc_now

logger = logging.getLogger(__name__)

_last_fetch: Optional[datetime] = None
_cached_board: Optional[SportsBoardResponse] = None

DECISION_MARKETS = ("h2h", "spreads", "totals")
# Snapshot rows from one board build differ by milliseconds; group within this.
_OPENING_BATCH_WINDOW_SECONDS = 600.0


def _opening_line(history: list[dict[str, Any]], market: str) -> Optional[dict[str, Any]]:
    """Best-across-books line from the earliest snapshot batch.

    History rows are per-bookmaker; comparing a single book's opener against
    today's best-across-books line would manufacture fake movement, so the
    opener is reconstructed the same way (best price per outcome across the
    books captured in the first scan)."""
    if not history:
        return None
    try:
        first_ts = parse_datetime(history[0]["snapshot_at"])
    except (TypeError, ValueError, KeyError):
        return None
    batch: list[dict[str, Any]] = []
    for row in history:
        try:
            ts = parse_datetime(row["snapshot_at"])
        except (TypeError, ValueError, KeyError):
            continue
        if (ts - first_ts).total_seconds() > _OPENING_BATCH_WINDOW_SECONDS:
            break
        batch.append(
            {
                "bookmaker": row.get("bookmaker", ""),
                "market": market,
                "outcomes": (row.get("line") or {}).get("outcomes", []),
            }
        )
    return best_market_line(batch, market)


def _is_live_window(commence_time: str, now: datetime) -> bool:
    try:
        commence = parse_datetime(commence_time)
    except (TypeError, ValueError):
        return False
    if commence.tzinfo is None:
        commence = commence.replace(tzinfo=now.tzinfo)
    hours = (commence - now).total_seconds() / 3600.0
    return -3 <= hours <= 6


async def build_sports_board(
    force: bool = False,
    *,
    sport_filter: Optional[str] = None,
) -> SportsBoardResponse:
    global _last_fetch, _cached_board
    now = utc_now()
    from config import settings

    if (
        not force
        and _cached_board
        and _last_fetch
        and (now - _last_fetch).total_seconds() < settings.sports_scan_interval_minutes * 60
    ):
        return _cached_board

    if not settings.odds_api_key:
        return SportsBoardResponse(
            configured=False,
            message="Add ODDS_API_KEY to .env for live sports odds",
            data_timestamp=now,
        )

    raw_events = await fetch_raw_odds_events(per_sport_limit=10)
    feed_keys: set[str] = set()
    for event in raw_events:
        feed_keys.update(feed_keys_for_sport(event.get("sport_key", "")))
    news_items = await collect_sports_news(sorted(feed_keys))
    enriched_events, news_counts = attach_news_to_events(raw_events, news_items)
    ranked_events = rank_events(
        enriched_events,
        news_counts=news_counts,
        now=now,
    )

    games: list[SportsGameCard] = []
    featured: set[str] = set()
    engine_decisions: list = []
    games_without_pricing = 0

    for item in ranked_events:
        sport = item.get("sport_key", "")
        if sport_filter and sport_filter not in sport:
            continue
        home = item.get("home_team", "")
        away = item.get("away_team", "")
        commence = item.get("commence_time", "")
        # Hard horizon: only show games within N days (default 3). Live games
        # stay visible on the board; decisions themselves require the game to
        # be strictly in the future (enforced inside analyze_game).
        if not within_bet_horizon(
            commence,
            now,
            horizon_days=settings.sports_bet_horizon_days,
            allow_live_hours=3.0,
        ):
            continue
        event_key = event_key_for(sport, home, away, commence)
        lines: list[SportsOddsLine] = []
        line_dicts: list[dict[str, Any]] = []

        # Full book depth feeds the decision engine — the cross-book edge
        # model needs every quote it can get; a 3-book sample structurally
        # starves it (the leave-one-out consensus collapses to 2 books).
        for bookmaker in item.get("bookmakers", [])[: settings.odds_max_bookmakers_decision]:
            for market in bookmaker.get("markets", []):
                outcomes = [
                    {"name": o.get("name"), "price": o.get("price"), "point": o.get("point")}
                    for o in market.get("outcomes", [])
                ]
                line = SportsOddsLine(
                    bookmaker=bookmaker.get("title", ""),
                    market=market.get("key", ""),
                    outcomes=outcomes,
                )
                lines.append(line)
                line_dicts.append(
                    {
                        "bookmaker": bookmaker.get("title", ""),
                        "market": market.get("key", ""),
                        "outcomes": outcomes,
                    }
                )
                await save_sports_odds_snapshot(
                    event_key=event_key,
                    sport=sport,
                    home_team=home,
                    away_team=away,
                    commence_time=commence,
                    market=market.get("key", ""),
                    bookmaker=bookmaker.get("title", ""),
                    line={"outcomes": outcomes},
                )

        movement_notes: dict[str, Optional[str]] = {}
        openings: dict[str, Optional[dict[str, Any]]] = {}
        for market_key in DECISION_MARKETS:
            history = await get_sports_odds_history(event_key, market_key, limit=200)
            market_opening = _opening_line(history, market_key)
            market_current = best_market_line(line_dicts, market_key)
            openings[market_key] = market_opening
            movement_notes[market_key] = line_movement_delta(market_opening, market_current)

        opening = openings.get("h2h")
        current = best_h2h_line(line_dicts)
        movement = movement_notes.get("h2h")

        news_context = [
            SportsNewsContext(
                title=n.get("title", ""),
                url=n.get("url", ""),
                source=n.get("source", ""),
                published=n.get("published", ""),
                matched_teams=n.get("matched_teams", []),
            )
            for n in item.get("news_context", [])
        ]

        decision = analyze_game(
            event_key=event_key,
            sport_key=sport,
            sport_title=item.get("sport_title", sport),
            home_team=home,
            away_team=away,
            commence_time=commence,
            line_dicts=line_dicts,
            movement_notes=movement_notes,
            news_count=len(news_context),
            now=now,
        )
        if decision:
            decision = (await finalize_decisions([decision]))[0]
            engine_decisions.append(decision)
        else:
            games_without_pricing += 1
        bet_decision = (
            SportsBetDecision.model_validate(decision_to_dict(decision)) if decision else None
        )

        ai_context_parts: list[str] = []
        if bet_decision:
            ai_context_parts.append(bet_decision.rationale)
        if movement:
            ai_context_parts.append(f"Line movement: {movement}")
        if news_context:
            ai_context_parts.append(f"{len(news_context)} matched news article(s)")
        ai_context = " · ".join(ai_context_parts) if ai_context_parts else None

        sport_title = item.get("sport_title", sport)
        if item.get("relevance_score", 0) >= 5:
            featured.add(sport_title)

        games.append(
            SportsGameCard(
                event_key=event_key,
                sport=sport,
                sport_key=sport,
                sport_title=sport_title,
                home_team=home,
                away_team=away,
                commence_time=commence,
                lines=lines,
                best_line=current,
                opening_line=opening,
                line_movement=movement,
                movement_delta=movement,
                fair_line=current.get("fair_outcomes") if current else None,
                relevance_score=float(item.get("relevance_score", 0)),
                relevance_factors=item.get("relevance_factors", {}),
                is_live_window=_is_live_window(commence, now),
                news_context=news_context,
                ai_context=ai_context,
                bet_decision=bet_decision,
                data_timestamp=now,
            )
        )

    best_bets = sorted(
        (g.bet_decision for g in games if g.bet_decision and g.bet_decision.decision == DECISION_BET),
        key=lambda d: -d.ev_pct,
    )
    top_setups = [
        SportsBetDecision.model_validate(decision_to_dict(d))
        for d in rank_setups(engine_decisions)
    ]
    scan_review = build_scan_review(
        engine_decisions, games_without_pricing=games_without_pricing
    )

    quota = get_last_odds_quota()
    board = SportsBoardResponse(
        games=games,
        configured=True,
        data_timestamp=now,
        featured_competitions=sorted(featured),
        active_sports_count=len({g.sport_key for g in games}),
        quota_remaining=quota.remaining,
        quota_used=quota.used,
        best_bets=best_bets,
        top_setups=top_setups,
        scan_review=scan_review,
        bet_horizon_days=settings.sports_bet_horizon_days,
    )
    _cached_board = board
    _last_fetch = now
    return board
