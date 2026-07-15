from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from config import settings
from pipeline.odds_relevance import markets_for_sport, rank_events, select_sports_to_fetch
from time_utils import utc_now

logger = logging.getLogger(__name__)

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

US_FALLBACK_SPORTS = [
    "americanfootball_nfl",
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
]


@dataclass
class OddsQuota:
    remaining: Optional[int] = None
    used: Optional[int] = None
    last_cost: Optional[int] = None


@dataclass
class OddsOutcome:
    name: str
    price: float
    point: Optional[float] = None


@dataclass
class OddsMarket:
    key: str
    outcomes: list[OddsOutcome] = field(default_factory=list)


@dataclass
class SportsEvent:
    sport: str
    sport_title: str
    home_team: str
    away_team: str
    commence_time: str
    event_id: str = ""
    markets: list[OddsMarket] = field(default_factory=list)
    relevance_score: float = 0.0
    relevance_factors: dict[str, float] = field(default_factory=dict)
    bookmaker_count: int = 0


_last_quota = OddsQuota()


def get_last_odds_quota() -> OddsQuota:
    return _last_quota


def _update_quota_from_headers(headers: httpx.Headers) -> None:
    global _last_quota
    remaining = headers.get("x-requests-remaining")
    used = headers.get("x-requests-used")
    last_cost = headers.get("x-requests-last")
    _last_quota = OddsQuota(
        remaining=int(remaining) if remaining is not None else _last_quota.remaining,
        used=int(used) if used is not None else _last_quota.used,
        last_cost=int(last_cost) if last_cost is not None else _last_quota.last_cost,
    )


async def discover_active_sports(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    if not settings.odds_api_key:
        return []
    url = f"{ODDS_API_BASE}/sports/"
    try:
        response = await client.get(url, params={"apiKey": settings.odds_api_key})
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []
    except httpx.HTTPError as exc:
        logger.warning("Odds sport discovery failed: %s", exc)
        return []


async def fetch_sport_odds(
    client: httpx.AsyncClient,
    sport_key: str,
    *,
    per_sport_limit: int = 10,
) -> list[dict[str, Any]]:
    if not settings.odds_api_key:
        return []
    markets = markets_for_sport(sport_key)
    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds/"
    params = {
        "apiKey": settings.odds_api_key,
        "regions": settings.odds_regions,
        "markets": markets,
        "oddsFormat": "american",
    }
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        _update_quota_from_headers(response.headers)
        payload = response.json()
        events: list[dict[str, Any]] = []
        for item in payload[:per_sport_limit]:
            item.setdefault("sport_key", sport_key)
            events.append(item)
        return events
    except httpx.HTTPError as exc:
        logger.warning("Odds fetch failed for %s: %s", sport_key, exc)
        return []


async def fetch_raw_odds_events(
    per_sport_limit: int = 10,
    *,
    max_sports: Optional[int] = None,
) -> list[dict[str, Any]]:
    if not settings.odds_api_key:
        return []

    max_sports = max_sports or settings.odds_max_sports_per_scan
    league_interest = settings.odds_league_interest_bias
    events: list[dict[str, Any]] = []
    sport_titles: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=20.0) as client:
        sport_keys = US_FALLBACK_SPORTS
        if settings.odds_dynamic_discovery:
            active = await discover_active_sports(client)
            for sport in active:
                key = sport.get("key", "")
                if key:
                    sport_titles[key] = sport.get("title", key)
            sport_keys = select_sports_to_fetch(
                active,
                max_sports=max_sports,
                league_interest=league_interest,
            )

        for sport in sport_keys:
            sport_events = await fetch_sport_odds(client, sport, per_sport_limit=per_sport_limit)
            events.extend(sport_events)

    ranked = rank_events(
        events,
        sport_titles=sport_titles,
        league_interest=league_interest,
        now=utc_now(),
    )
    return ranked[: settings.odds_max_events]


def _to_sports_event(item: dict[str, Any]) -> SportsEvent:
    sport = item.get("sport_key", "")
    bookmakers = item.get("bookmakers", []) or []
    markets: list[OddsMarket] = []
    for bookmaker in bookmakers[: settings.odds_max_bookmakers_briefing]:
        for market in bookmaker.get("markets", []):
            outcomes = [
                OddsOutcome(
                    name=o.get("name", ""),
                    price=float(o.get("price", 0)),
                    point=o.get("point"),
                )
                for o in market.get("outcomes", [])
            ]
            markets.append(OddsMarket(key=market.get("key", ""), outcomes=outcomes))

    return SportsEvent(
        sport=sport,
        sport_title=item.get("sport_title", sport),
        home_team=item.get("home_team", ""),
        away_team=item.get("away_team", ""),
        commence_time=item.get("commence_time", ""),
        event_id=item.get("id", ""),
        markets=markets,
        relevance_score=float(item.get("relevance_score", 0)),
        relevance_factors=item.get("relevance_factors", {}),
        bookmaker_count=len(bookmakers),
    )


async def fetch_event_scores(sport_key: str, days_from: int = 1) -> list[dict[str, Any]]:
    if not settings.odds_api_key:
        return []
    url = f"{ODDS_API_BASE}/sports/{sport_key}/scores/"
    params = {
        "apiKey": settings.odds_api_key,
        "daysFrom": days_from,
        "dateFormat": "iso",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            _update_quota_from_headers(response.headers)
            payload = response.json()
            return payload if isinstance(payload, list) else []
        except httpx.HTTPError as exc:
            logger.warning("Scores fetch failed for %s: %s", sport_key, exc)
            return []


async def collect_sports_odds(limit: Optional[int] = None) -> list[SportsEvent]:
    raw_events = await fetch_raw_odds_events(per_sport_limit=8)
    if limit is not None:
        raw_events = raw_events[:limit]
    return [_to_sports_event(item) for item in raw_events]
