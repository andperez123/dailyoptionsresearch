from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Optional

from database import get_sports_odds_history, save_sports_odds_snapshot
from models import SportsBoardResponse, SportsGameCard, SportsOddsLine
from pipeline.odds import fetch_raw_odds_events
from time_utils import utc_now

logger = logging.getLogger(__name__)

_last_fetch: Optional[datetime] = None
_cached_board: Optional[SportsBoardResponse] = None


def _event_key(sport: str, home: str, away: str, commence: str) -> str:
    raw = f"{sport}|{home}|{away}|{commence}"
    return hashlib.md5(raw.encode()).hexdigest()


def _best_line(lines: list[SportsOddsLine], market: str) -> Optional[dict[str, Any]]:
    market_lines = [line for line in lines if line.market == market]
    if not market_lines:
        return None
    best = market_lines[0]
    return {"bookmaker": best.bookmaker, "outcomes": best.outcomes}


async def build_sports_board(force: bool = False) -> SportsBoardResponse:
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
    games: list[SportsGameCard] = []

    for item in raw_events:
        sport = item.get("sport_key", "")
        home = item.get("home_team", "")
        away = item.get("away_team", "")
        commence = item.get("commence_time", "")
        event_key = _event_key(sport, home, away, commence)
        lines: list[SportsOddsLine] = []

        for bookmaker in item.get("bookmakers", [])[:3]:
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
        current = _best_line(lines, "h2h")
        movement = None
        if opening and current and len(history) > 1:
            movement = "Line moved since first snapshot"

        ai_context = None
        if movement:
            ai_context = "Observation: line movement detected — verify whether news is fully reflected"

        games.append(
            SportsGameCard(
                sport=sport,
                home_team=home,
                away_team=away,
                commence_time=commence,
                lines=lines,
                best_line=current,
                opening_line=opening,
                line_movement=movement,
                ai_context=ai_context,
                data_timestamp=now,
            )
        )

    board = SportsBoardResponse(games=games, configured=True, data_timestamp=now)
    _cached_board = board
    _last_fetch = now
    return board
