from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Optional

from database import get_sports_odds_history, save_sports_odds_snapshot
from models import SportsBoardResponse, SportsGameCard, SportsNewsContext, SportsOddsLine
from pipeline.odds import fetch_raw_odds_events, get_last_odds_quota
from pipeline.odds_math import best_h2h_line, line_movement_delta
from pipeline.odds_relevance import rank_events
from pipeline.sports_news import attach_news_to_events, collect_sports_news, feed_keys_for_sport
from time_utils import parse_datetime, utc_now

logger = logging.getLogger(__name__)

_last_fetch: Optional[datetime] = None
_cached_board: Optional[SportsBoardResponse] = None


def _event_key(sport: str, home: str, away: str, commence: str) -> str:
    raw = f"{sport}|{home}|{away}|{commence}"
    return hashlib.md5(raw.encode()).hexdigest()


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

    for item in ranked_events:
        sport = item.get("sport_key", "")
        if sport_filter and sport_filter not in sport:
            continue
        home = item.get("home_team", "")
        away = item.get("away_team", "")
        commence = item.get("commence_time", "")
        event_key = _event_key(sport, home, away, commence)
        lines: list[SportsOddsLine] = []
        line_dicts: list[dict[str, Any]] = []

        for bookmaker in item.get("bookmakers", [])[: settings.odds_max_bookmakers_briefing]:
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

        history = await get_sports_odds_history(event_key, "h2h", limit=5)
        opening = history[0]["line"] if history else None
        current = best_h2h_line(line_dicts)
        movement = line_movement_delta(opening, current)

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

        ai_context_parts: list[str] = []
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
                data_timestamp=now,
            )
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
    )
    _cached_board = board
    _last_fetch = now
    return board
