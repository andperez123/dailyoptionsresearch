from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Optional

import feedparser
import httpx

from pipeline.news import fetch_feed

SPORTS_FEEDS: dict[str, str] = {
    "soccer": "https://www.espn.com/espn/rss/soccer/news",
    "nfl": "https://www.espn.com/espn/rss/nfl/news",
    "nba": "https://www.espn.com/espn/rss/nba/news",
    "mlb": "https://www.espn.com/espn/rss/mlb/news",
    "nhl": "https://www.espn.com/espn/rss/nhl/news",
}

SPORT_KEY_TO_FEED: dict[str, str] = {
    "soccer": "soccer",
    "americanfootball": "nfl",
    "basketball": "nba",
    "baseball": "mlb",
    "icehockey": "nhl",
}


@dataclass
class SportsNewsItem:
    title: str
    url: str
    source: str
    published: str
    feed_key: str
    matched_teams: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.matched_teams is None:
            self.matched_teams = []


def _normalize_team(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _team_tokens(name: str) -> set[str]:
    normalized = _normalize_team(name)
    tokens = {t for t in normalized.split() if len(t) > 2}
    if normalized:
        tokens.add(normalized)
    return tokens


def match_teams_in_text(text: str, home_team: str, away_team: str) -> list[str]:
    haystack = text.lower()
    matched: list[str] = []
    for team in (home_team, away_team):
        tokens = _team_tokens(team)
        if any(token in haystack for token in tokens):
            matched.append(team)
    return matched


def feed_keys_for_sport(sport_key: str) -> list[str]:
    if sport_key.startswith("soccer"):
        return ["soccer"]
    prefix = sport_key.split("_", 1)[0]
    feed = SPORT_KEY_TO_FEED.get(prefix)
    return [feed] if feed else list(SPORTS_FEEDS.keys())


async def collect_sports_news(feed_keys: Optional[list[str]] = None) -> list[SportsNewsItem]:
    keys = feed_keys or list(SPORTS_FEEDS.keys())
    tasks = [fetch_feed(SPORTS_FEEDS[key]) for key in keys if key in SPORTS_FEEDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    items: list[SportsNewsItem] = []
    seen: set[str] = set()
    for key, result in zip([k for k in keys if k in SPORTS_FEEDS], results):
        if isinstance(result, Exception):
            continue
        for item in result:
            if not item.url or item.url in seen:
                continue
            seen.add(item.url)
            items.append(
                SportsNewsItem(
                    title=item.title,
                    url=item.url,
                    source=item.source or f"ESPN {key.upper()}",
                    published=item.published,
                    feed_key=key,
                )
            )
    return items


def attach_news_to_events(
    events: list[dict[str, Any]],
    news_items: list[SportsNewsItem],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    news_counts: dict[str, int] = {}
    enriched: list[dict[str, Any]] = []
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        event_key = event.get("id") or f"{event.get('sport_key')}|{home}|{away}|{event.get('commence_time')}"
        matched_articles: list[dict[str, Any]] = []
        for article in news_items:
            teams = match_teams_in_text(f"{article.title} {article.url}", home, away)
            if teams:
                matched_articles.append(
                    {
                        "title": article.title,
                        "url": article.url,
                        "source": article.source,
                        "published": article.published,
                        "matched_teams": teams,
                    }
                )
        news_counts[event_key] = len(matched_articles)
        enriched.append({**event, "news_context": matched_articles[:5]})
    return enriched, news_counts
