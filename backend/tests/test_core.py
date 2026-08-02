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
from pipeline.synthesis import _parse_model_json, select_top_tickers, validate_sports_angles
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


def test_parse_model_json_handles_markdown_fence() -> None:
    raw = 'Here is the briefing:\n```json\n{"summary": "ok", "narratives": []}\n```'
    data = _parse_model_json(raw)
    assert data["summary"] == "ok"


def test_parse_model_json_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        _parse_model_json("   ")


def test_propose_strategies_prefers_spreads_when_iv_elevated() -> None:
    from pipeline.strategies import propose_strategies

    proposals = propose_strategies(
        ticker="NVDA",
        price=140.0,
        nearest_expiry="2026-08-08",
        next_expiry="2026-08-15",
        avg_iv=0.65,
        put_call_ratio=0.6,
        catalyst_direction="bullish",
        limit=3,
    )
    assert proposals
    types = {p.strategy_type for p in proposals}
    assert "debit_call_spread" in types or "credit_put_spread" in types
    assert all(p.strategy_type not in {"long_call", "long_put"} for p in proposals)
    assert all(len(p.legs) >= 2 for p in proposals)


def test_propose_strategies_event_bias_includes_strangle() -> None:
    from pipeline.strategies import propose_strategies

    proposals = propose_strategies(
        ticker="AAPL",
        price=200.0,
        nearest_expiry="2026-08-08",
        next_expiry="2026-09-19",
        avg_iv=0.4,
        catalyst_direction="volatility",
        catalyst_type="earnings",
        limit=4,
    )
    types = {p.strategy_type for p in proposals}
    assert "long_strangle" in types or "calendar_call" in types


def test_build_ticker_dossiers_corroborates_multi_domain_news() -> None:
    from pipeline.news import NewsItem
    from pipeline.options import OptionsSnapshot
    from pipeline.research import build_ticker_dossiers

    news = [
        NewsItem(
            title="Acme wins major cloud contract deal",
            url="https://www.reuters.com/acme-1",
            source="Reuters",
            published=utc_now().isoformat(),
            ticker="ACME",
            source_tier="finnhub",
            summary="Acme secured a multi-year cloud deal.",
        ),
        NewsItem(
            title="Acme wins major cloud contract award",
            url="https://www.cnbc.com/acme-2",
            source="CNBC",
            published=utc_now().isoformat(),
            ticker="ACME",
            source_tier="rss",
            summary="Analysts lift targets after contract win.",
        ),
    ]
    dossiers = build_ticker_dossiers(
        tickers=["ACME"],
        news=news,
        finance_posts=[],
        options=[OptionsSnapshot(ticker="ACME", current_price=50.0, nearest_expiry=None, error="No chain")],
        overnight_catalysts=[],
        ticker_counts={"ACME": 5},
        buzz_deltas={"ACME": 1.2},
        max_age_hours=24,
    )
    assert len(dossiers) == 1
    quality = dossiers[0]["research_quality"]
    assert quality["news_domain_count"] >= 2
    assert quality["meets_multi_source_bar"] is True
    assert quality["independent_source_count"] >= 2


def test_validate_narratives_drops_single_source_when_required() -> None:
    from pipeline.research import validate_narratives

    dossiers = [
        {
            "ticker": "ACME",
            "research_quality": {
                "independent_source_count": 1,
                "distinct_domains": ["reddit.com"],
                "source_types": ["reddit"],
                "corroborated_claim_count": 0,
                "meets_multi_source_bar": False,
                "news_domain_count": 0,
            },
            "sources": [],
            "strategy_candidates": [
                {
                    "ticker": "ACME",
                    "direction": "bullish",
                    "strategy_type": "debit_call_spread",
                    "structure": "Buy 50C / Sell 55C",
                    "strike_zone": "$50/$55",
                    "expiry": "2026-08-08",
                    "legs": [],
                    "degen_score": 2,
                    "risk_note": "",
                    "iv_note": "",
                    "edge": "defined risk",
                }
            ],
        }
    ]
    kept = validate_narratives(
        [{"title": "Weak", "tickers": ["ACME"], "sources": [], "options_plays": [{"direction": "call", "ticker": "ACME", "strike_zone": "calls", "expiry": "weekly", "degen_score": 4}]}],
        dossiers,
        require_multi_source=True,
    )
    assert kept == []

    soft = validate_narratives(
        [{"title": "Weak", "tickers": ["ACME"], "sources": [], "options_plays": [{"direction": "call", "ticker": "ACME", "strike_zone": "calls", "expiry": "weekly", "degen_score": 4}]}],
        dossiers,
        require_multi_source=False,
    )
    assert len(soft) == 1
    assert soft[0]["options_plays"][0]["strategy_type"] == "debit_call_spread"


def _mispriced_lines() -> list[dict]:
    """Three sharp books price Team A ~ -150; one soft book hangs +105."""
    sharp = {
        "market": "h2h",
        "outcomes": [{"name": "Team A", "price": -150}, {"name": "Team B", "price": 130}],
    }
    return [
        {**sharp, "bookmaker": "Book 1"},
        {**sharp, "bookmaker": "Book 2"},
        {**sharp, "bookmaker": "Book 3"},
        {
            "bookmaker": "Soft Book",
            "market": "h2h",
            "outcomes": [{"name": "Team A", "price": 105}, {"name": "Team B", "price": -125}],
        },
    ]


def test_evaluate_market_finds_edge_at_soft_book() -> None:
    from pipeline.sports_strategies import evaluate_market

    candidates = evaluate_market(_mispriced_lines(), "h2h", min_books=2)
    assert candidates
    best = candidates[0]
    assert best.selection == "Team A"
    assert best.best_bookmaker == "Soft Book"
    assert best.best_price == 105
    assert best.edge_pct > 2.0
    assert best.ev_pct > 3.0


def test_analyze_game_bets_mispriced_outcome_within_horizon() -> None:
    from pipeline.sports_strategies import analyze_game

    now = utc_now()
    decision = analyze_game(
        event_key="evt1",
        sport_key="basketball_nba",
        sport_title="NBA",
        home_team="Home",
        away_team="Away",
        commence_time=(now + timedelta(hours=24)).isoformat(),
        line_dicts=_mispriced_lines(),
        news_count=2,
        now=now,
    )
    assert decision is not None
    assert decision.decision == "bet"
    assert decision.selection == "Team A"
    assert decision.stake_units > 0
    assert decision.confidence > 0
    assert decision.research_checklist
    assert any("rest" in item.lower() or "back-to-back" in item.lower() for item in decision.research_checklist)


def test_analyze_game_rejects_games_beyond_horizon() -> None:
    from pipeline.sports_strategies import analyze_game, within_bet_horizon

    now = utc_now()
    far_out = (now + timedelta(days=5)).isoformat()
    assert not within_bet_horizon(far_out, now, horizon_days=3)
    decision = analyze_game(
        event_key="evt2",
        sport_key="basketball_nba",
        sport_title="NBA",
        home_team="Home",
        away_team="Away",
        commence_time=far_out,
        line_dicts=_mispriced_lines(),
        now=now,
    )
    assert decision is None


def test_analyze_game_passes_on_efficient_market() -> None:
    from pipeline.sports_strategies import analyze_game

    now = utc_now()
    efficient = {
        "market": "h2h",
        "outcomes": [{"name": "Team A", "price": -110}, {"name": "Team B", "price": -110}],
    }
    decision = analyze_game(
        event_key="evt3",
        sport_key="americanfootball_nfl",
        sport_title="NFL",
        home_team="Home",
        away_team="Away",
        commence_time=(now + timedelta(hours=12)).isoformat(),
        line_dicts=[
            {**efficient, "bookmaker": "Book 1"},
            {**efficient, "bookmaker": "Book 2"},
            {**efficient, "bookmaker": "Book 3"},
        ],
        now=now,
    )
    assert decision is not None
    assert decision.decision == "pass"
    assert decision.stake_units == 0


def test_kelly_fraction_positive_only_with_edge() -> None:
    from pipeline.sports_strategies import kelly_fraction

    assert kelly_fraction(0.55, 105) > 0
    assert kelly_fraction(0.45, -110) == 0.0


def test_validate_sports_angles_attaches_engine_decision() -> None:
    from pipeline.sports_strategies import analyze_raw_events

    now = utc_now()
    raw_event = {
        "id": "wc1",
        "sport_key": "soccer_fifa_world_cup",
        "sport_title": "FIFA World Cup",
        "home_team": "France",
        "away_team": "Brazil",
        "commence_time": (now + timedelta(hours=20)).isoformat(),
        "bookmakers": [
            {
                "title": bookmaker,
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "France", "price": -150 if bookmaker != "Soft" else 105},
                            {"name": "Brazil", "price": 130 if bookmaker != "Soft" else -125},
                        ],
                    }
                ],
            }
            for bookmaker in ("Book 1", "Book 2", "Book 3", "Soft")
        ],
    }
    decisions = analyze_raw_events([raw_event], now=now)
    assert decisions and decisions[0].decision == "bet"

    odds = [
        SportsEvent(
            sport="soccer_fifa_world_cup",
            sport_title="FIFA World Cup",
            home_team="France",
            away_team="Brazil",
            commence_time=raw_event["commence_time"],
            event_id="wc1",
        )
    ]
    valid = validate_sports_angles(
        [
            {
                "title": "Value on France",
                "sport": "FIFA World Cup",
                "matchup": "Brazil @ France",
                "narrative": "Soft book hanging a stale number",
                "sources": [{"title": "ESPN", "url": "https://espn.com/story", "source_type": "news"}],
                "degen_score": 3,
            }
        ],
        odds,
        [],
        bet_decisions=decisions,
    )
    assert len(valid) == 1
    assert valid[0].bet_decision is not None
    assert valid[0].bet_decision.decision == "bet"
    assert valid[0].bet_decision.selection == "France"


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
