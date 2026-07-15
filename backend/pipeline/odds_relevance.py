from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from time_utils import parse_datetime

STAGE_KEYWORDS: list[tuple[str, float]] = [
    (r"\bfinal\b", 4.0),
    (r"\bsemifinal\b", 3.5),
    (r"\bquarterfinal\b", 3.0),
    (r"\bknockout\b", +2.5),
    (r"\bplayoff\b", 2.5),
    (r"\bchampionship\b", 3.0),
    (r"\bworld[_ ]?cup\b", 3.0),
    (r"\bfifa\b", 2.5),
    (r"\belimination\b", 2.0),
    (r"\bgroup stage\b", 1.0),
]

US_FALLBACK_SPORTS = [
    "americanfootball_nfl",
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
]


def _parse_commence(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parse_datetime(value)
    except (TypeError, ValueError):
        return None


def stage_significance(*texts: str) -> float:
    combined = " ".join(t.lower() for t in texts if t)
    score = 0.0
    for pattern, weight in STAGE_KEYWORDS:
        if re.search(pattern, combined):
            score = max(score, weight)
    return score


def proximity_score(commence: Optional[datetime], now: datetime) -> float:
    if commence is None:
        return 0.0
    if commence.tzinfo is None:
        commence = commence.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    hours = (commence - now).total_seconds() / 3600.0
    if -3 <= hours <= 0:
        return 8.0
    if 0 < hours <= 6:
        return 7.0
    if 6 < hours <= 24:
        return 5.0
    if 24 < hours <= 72:
        return 3.0
    if hours < -3:
        return 1.0
    return 0.5


def markets_for_sport(sport_key: str) -> str:
    if sport_key.startswith("soccer"):
        return "h2h"
    return "h2h,spreads,totals"


def score_event_relevance(
    event: dict[str, Any],
    *,
    sport_title: str = "",
    league_interest_bias: float = 0.0,
    news_hits: int = 0,
    movement_detected: bool = False,
    now: Optional[datetime] = None,
) -> tuple[float, dict[str, float]]:
    now = now or datetime.now(timezone.utc)
    sport_key = event.get("sport_key", "")
    commence = _parse_commence(event.get("commence_time", ""))
    bookmakers = event.get("bookmakers", []) or []
    book_depth = len(bookmakers)

    factors = {
        "proximity": proximity_score(commence, now),
        "stage": stage_significance(sport_key, sport_title, event.get("home_team", ""), event.get("away_team", "")),
        "book_depth": min(book_depth, 10) * 0.3,
        "news_hits": min(news_hits, 5) * 0.8,
        "movement": 1.5 if movement_detected else 0.0,
        "league_bias": league_interest_bias,
    }
    total = sum(factors.values())
    return round(total, 2), factors


def rank_events(
    events: list[dict[str, Any]],
    *,
    sport_titles: Optional[dict[str, str]] = None,
    league_interest: Optional[dict[str, float]] = None,
    news_counts: Optional[dict[str, int]] = None,
    movement_keys: Optional[set[str]] = None,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    sport_titles = sport_titles or {}
    league_interest = league_interest or {}
    news_counts = news_counts or {}
    movement_keys = movement_keys or set()
    now = now or datetime.now(timezone.utc)

    scored: list[tuple[float, dict[str, Any]]] = []
    for event in events:
        sport_key = event.get("sport_key", "")
        event_key = event.get("id") or f"{sport_key}|{event.get('home_team')}|{event.get('away_team')}|{event.get('commence_time')}"
        score, factors = score_event_relevance(
            event,
            sport_title=sport_titles.get(sport_key, sport_key),
            league_interest_bias=league_interest.get(sport_key, 0.0),
            news_hits=news_counts.get(event_key, 0),
            movement_detected=event_key in movement_keys,
            now=now,
        )
        enriched = {**event, "relevance_score": score, "relevance_factors": factors}
        scored.append((score, enriched))

    scored.sort(
        key=lambda pair: (
            -pair[0],
            pair[1].get("commence_time", ""),
        )
    )
    return [event for _, event in scored]


def select_sports_to_fetch(
    active_sports: list[dict[str, Any]],
    *,
    max_sports: int = 8,
    league_interest: Optional[dict[str, float]] = None,
) -> list[str]:
    league_interest = league_interest or {}
    active = [s for s in active_sports if s.get("active")]
    if not active:
        return US_FALLBACK_SPORTS[:max_sports]

    def sort_key(sport: dict[str, Any]) -> tuple[float, str]:
        key = sport.get("key", "")
        title = sport.get("title", key)
        bias = league_interest.get(key, 0.0)
        stage = stage_significance(key, title, sport.get("group", ""))
        return (-(stage + bias), key)

    active.sort(key=sort_key)
    keys = [s["key"] for s in active if s.get("key")][:max_sports]
    if not keys:
        return US_FALLBACK_SPORTS[:max_sports]
    return keys
