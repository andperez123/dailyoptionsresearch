from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database import _parse_dt
from pipeline.catalyst import _match_ai_results, cluster_key_for
from pipeline.finnhub import NormalizedHeadline
from pipeline.odds_math import (
    american_to_implied_prob,
    best_h2h_line,
    line_movement_delta,
    remove_vig,
)
from pipeline.odds_relevance import (
    rank_events,
    score_event_relevance,
    select_sports_to_fetch,
    stage_significance,
)
from pipeline.odds import SportsEvent
from pipeline.sports_news import match_teams_in_text
from pipeline.synthesis import select_top_tickers, validate_sports_angles
from time_utils import parse_datetime, utc_now


def test_parse_datetime_handles_z_suffix() -> None:
    parsed = parse_datetime("2026-07-14T12:00:00Z")
    assert parsed.tzinfo is not None
    assert parsed.year == 2026


def test_database_parse_dt_matches_time_utils() -> None:
    value = "2026-07-14T12:00:00+00:00"
    assert _parse_dt(value) == parse_datetime(value)


def test_cluster_key_is_stable_for_same_headline() -> None:
    headline = "Apple raises guidance after strong quarter"
    assert cluster_key_for(headline, "AAPL") == cluster_key_for(headline, "AAPL")


def test_match_ai_results_by_headline_not_index() -> None:
    items = [
        (
            NormalizedHeadline(
                provider="rss",
                external_id="1",
                headline="Headline A",
                summary="",
                url="",
                published_at=utc_now(),
                related_tickers=["AAA"],
                raw_payload={},
            ),
            {},
            {"impact_score": 1, "confidence_score": 1, "novelty_score": 1},
        ),
        (
            NormalizedHeadline(
                provider="rss",
                external_id="2",
                headline="Headline B",
                summary="",
                url="",
                published_at=utc_now(),
                related_tickers=["BBB"],
                raw_payload={},
            ),
            {},
            {"impact_score": 2, "confidence_score": 2, "novelty_score": 2},
        ),
    ]
    ai_results = [
        {"headline": "Headline B", "impact_score": 9, "confidence_score": 8, "novelty_score": 7},
        {"headline": "Headline A", "impact_score": 4, "confidence_score": 3, "novelty_score": 2},
    ]
    matched = _match_ai_results(items, ai_results)
    assert matched[0]["impact_score"] == 4
    assert matched[1]["impact_score"] == 9


def test_select_top_tickers_sorts_by_count() -> None:
    counts = {"ZZZ": 1, "AAA": 10, "BBB": 5}
    assert select_top_tickers(counts, limit=2) == ["AAA", "BBB"]


def test_american_to_implied_prob() -> None:
    assert round(american_to_implied_prob(-110), 3) == 0.524
    assert round(american_to_implied_prob(150), 3) == 0.4


def test_remove_vig_normalizes_probabilities() -> None:
    fair = remove_vig(
        [
            {"name": "Team A", "price": -110},
            {"name": "Team B", "price": -110},
        ]
    )
    total = sum(item["fair_probability"] for item in fair)
    assert round(total, 3) == 1.0


def test_best_h2h_line_picks_best_prices() -> None:
    best = best_h2h_line(
        [
            {
                "bookmaker": "Book A",
                "market": "h2h",
                "outcomes": [{"name": "Team A", "price": -120}, {"name": "Team B", "price": 100}],
            },
            {
                "bookmaker": "Book B",
                "market": "h2h",
                "outcomes": [{"name": "Team A", "price": -105}, {"name": "Team B", "price": 110}],
            },
        ]
    )
    assert best is not None
    prices = {o["name"]: o["price"] for o in best["outcomes"]}
    assert prices["Team A"] == -105
    assert prices["Team B"] == 110


def test_line_movement_delta_detects_changes() -> None:
    opening = {"outcomes": [{"name": "Team A", "price": -120}]}
    current = {"outcomes": [{"name": "Team A", "price": -105}]}
    delta = line_movement_delta(opening, current)
    assert delta is not None
    assert "Team A" in delta


def test_stage_significance_prefers_knockout_language() -> None:
    assert stage_significance("soccer_fifa_world_cup", "World Cup Semifinal") > stage_significance(
        "baseball_mlb", "Regular season"
    )


def test_rank_events_prefers_near_term_major_event() -> None:
    now = datetime(2026, 7, 14, 18, 0, tzinfo=timezone.utc)
    world_cup = {
        "id": "wc1",
        "sport_key": "soccer_fifa_world_cup",
        "home_team": "France",
        "away_team": "Brazil",
        "commence_time": (now + timedelta(hours=4)).isoformat(),
        "bookmakers": [{}, {}, {}],
    }
    nfl_preseason = {
        "id": "nfl1",
        "sport_key": "americanfootball_nfl",
        "home_team": "Cowboys",
        "away_team": "Giants",
        "commence_time": (now + timedelta(days=40)).isoformat(),
        "bookmakers": [{}],
    }
    ranked = rank_events([nfl_preseason, world_cup], now=now)
    assert ranked[0]["sport_key"] == "soccer_fifa_world_cup"


def test_select_sports_to_fetch_uses_active_catalog() -> None:
    active = [
        {"key": "soccer_fifa_world_cup", "active": True, "title": "FIFA World Cup"},
        {"key": "americanfootball_nfl", "active": True, "title": "NFL"},
        {"key": "basketball_nba", "active": False, "title": "NBA"},
    ]
    keys = select_sports_to_fetch(active, max_sports=2)
    assert "soccer_fifa_world_cup" in keys


def test_match_teams_in_text() -> None:
    matched = match_teams_in_text("France advances past Brazil in semifinal", "France", "Brazil")
    assert "France" in matched
    assert "Brazil" in matched


def test_validate_sports_angles_requires_matching_event_and_sources() -> None:
    odds = [
        SportsEvent(
            sport="soccer_fifa_world_cup",
            sport_title="FIFA World Cup",
            home_team="France",
            away_team="Brazil",
            commence_time="2026-07-15T20:00:00Z",
            event_id="wc1",
        )
    ]
    valid = validate_sports_angles(
        [
            {
                "title": "Semifinal narrative",
                "sport": "FIFA World Cup",
                "matchup": "Brazil @ France",
                "narrative": "High-stakes rematch",
                "sources": [{"title": "ESPN", "url": "https://espn.com/story", "source_type": "news"}],
                "degen_score": 3,
            }
        ],
        odds,
        [],
    )
    assert len(valid) == 1
    assert valid[0].matchup == "Brazil @ France"

    dropped = validate_sports_angles(
        [
            {
                "title": "Fake game",
                "sport": "NFL",
                "matchup": "Fake @ Teams",
                "narrative": "Not real",
                "sources": [{"title": "X", "url": "https://example.com", "source_type": "web"}],
                "degen_score": 2,
            }
        ],
        odds,
        [],
    )
    assert dropped == []


def test_score_event_relevance_increases_with_news_hits() -> None:
    event = {
        "sport_key": "soccer_epl",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "commence_time": (utc_now() + timedelta(hours=2)).isoformat(),
        "bookmakers": [{}, {}],
    }
    low, _ = score_event_relevance(event, news_hits=0)
    high, _ = score_event_relevance(event, news_hits=4)
    assert high > low
