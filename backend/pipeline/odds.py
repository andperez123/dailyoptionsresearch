from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

SPORTS = ["americanfootball_nfl", "basketball_nba", "baseball_mlb", "icehockey_nhl"]


@dataclass
class OddsOutcome:
    name: str
    price: float


@dataclass
class OddsMarket:
    key: str
    outcomes: list[OddsOutcome] = field(default_factory=list)


@dataclass
class SportsEvent:
    sport: str
    home_team: str
    away_team: str
    commence_time: str
    markets: list[OddsMarket] = field(default_factory=list)


async def fetch_raw_odds_events(per_sport_limit: int = 10) -> list[dict[str, Any]]:
    if not settings.odds_api_key:
        return []

    events: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        for sport in SPORTS:
            url = (
                "https://api.the-odds-api.com/v4/sports/"
                f"{sport}/odds/?apiKey={settings.odds_api_key}"
                "&regions=us&markets=h2h,spreads,totals&oddsFormat=american"
            )
            try:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
                for item in payload[:per_sport_limit]:
                    item.setdefault("sport_key", sport)
                    events.append(item)
            except httpx.HTTPError as exc:
                logger.warning("Odds fetch failed for %s: %s", sport, exc)
    return events


def _to_sports_event(item: dict[str, Any]) -> SportsEvent:
    sport = item.get("sport_key", "")
    markets: list[OddsMarket] = []
    for bookmaker in item.get("bookmakers", [])[:1]:
        for market in bookmaker.get("markets", []):
            outcomes = [
                OddsOutcome(name=o.get("name", ""), price=float(o.get("price", 0)))
                for o in market.get("outcomes", [])
            ]
            markets.append(OddsMarket(key=market.get("key", ""), outcomes=outcomes))

    return SportsEvent(
        sport=sport,
        home_team=item.get("home_team", ""),
        away_team=item.get("away_team", ""),
        commence_time=item.get("commence_time", ""),
        markets=markets,
    )


async def collect_sports_odds() -> list[SportsEvent]:
    raw_events = await fetch_raw_odds_events(per_sport_limit=8)
    return [_to_sports_event(item) for item in raw_events]
