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


def _near_expiry(days: int = 7) -> str:
    from datetime import date as _date

    return (_date.today() + timedelta(days=days)).isoformat()


def test_propose_strategies_prefers_spreads_when_iv_elevated() -> None:
    from pipeline.strategies import propose_strategies

    proposals = propose_strategies(
        ticker="NVDA",
        price=140.0,
        nearest_expiry=_near_expiry(7),
        next_expiry=_near_expiry(14),
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
        nearest_expiry=_near_expiry(7),
        next_expiry=_near_expiry(49),
        avg_iv=0.4,
        catalyst_direction="volatility",
        catalyst_type="earnings",
        limit=4,
    )
    types = {p.strategy_type for p in proposals}
    assert "long_strangle" in types or "calendar_call" in types


def _fake_chain(strikes: list[float], low_oi_strikes: set[float] | None = None) -> dict:
    """Chain with call mids declining and put mids rising in strike."""
    low_oi_strikes = low_oi_strikes or set()
    chain: dict[float, dict] = {}
    for strike in strikes:
        call_mid = max(0.1, round(8.0 - 0.5 * (strike - 90.0), 2))
        put_mid = max(0.1, round(0.5 * (strike - 90.0) + 0.3, 2))
        oi = 5 if strike in low_oi_strikes else 500
        chain[strike] = {
            "call": {
                "bid": call_mid - 0.05,
                "ask": call_mid + 0.05,
                "mid": call_mid,
                "oi": oi,
                "volume": 50,
                "iv": 0.6,
            },
            "put": {
                "bid": put_mid - 0.05,
                "ask": put_mid + 0.05,
                "mid": put_mid,
                "oi": oi,
                "volume": 50,
                "iv": 0.62,
            },
        }
    return chain


def test_propose_strategies_snaps_strikes_to_liquid_chain() -> None:
    from pipeline.strategies import propose_strategies

    expiry = _near_expiry(10)
    strikes = [90.0, 92.5, 95.0, 97.5, 100.0, 102.5, 105.0, 107.5, 110.0]
    chains = {expiry: _fake_chain(strikes, low_oi_strikes={105.0})}

    proposals = propose_strategies(
        ticker="ACME",
        price=100.0,
        nearest_expiry=expiry,
        avg_iv=0.6,
        catalyst_direction="bullish",
        limit=3,
        atm_iv=0.6,
        chains=chains,
        min_leg_open_interest=100,
        max_leg_spread_pct=15.0,
    )
    assert proposals
    listed = set(strikes) - {105.0}
    for proposal in proposals:
        for leg in proposal.legs:
            assert float(leg["strike"]) in listed, f"{proposal.strategy_type} leg off-chain"
    # Priced from mids — risk strings should carry real dollar amounts
    debit_spread = next(p for p in proposals if p.strategy_type == "debit_call_spread")
    assert "$" in debit_spread.max_loss and "debit" in debit_spread.max_loss
    assert debit_spread.breakeven.startswith("$")


def test_propose_strategies_skips_premium_selling_near_expiry() -> None:
    from pipeline.strategies import propose_strategies

    proposals = propose_strategies(
        ticker="ACME",
        price=100.0,
        nearest_expiry=_near_expiry(1),
        avg_iv=0.7,
        catalyst_direction="neutral",
        limit=6,
    )
    types = {p.strategy_type for p in proposals}
    assert not types & {"iron_condor", "iron_butterfly", "credit_put_spread", "credit_call_spread"}


def test_propose_strategies_gates_risk_reversal_on_skew() -> None:
    from pipeline.strategies import propose_strategies

    common = dict(
        ticker="ACME",
        price=100.0,
        nearest_expiry=_near_expiry(10),
        next_expiry=_near_expiry(40),
        avg_iv=0.25,
        catalyst_direction="bullish",
        limit=6,
    )
    rich_put_skew = propose_strategies(**common, iv_skew=0.05)
    assert "risk_reversal" in {p.strategy_type for p in rich_put_skew}
    call_skew = propose_strategies(**common, iv_skew=-0.05)
    assert "risk_reversal" not in {p.strategy_type for p in call_skew}


def test_compute_iv_rank_requires_history() -> None:
    from pipeline.strategies import compute_iv_rank

    assert compute_iv_rank([0.4] * 5, 0.5) is None
    history = [0.30, 0.32, 0.35, 0.31, 0.33, 0.36, 0.34, 0.38, 0.40, 0.37]
    rank = compute_iv_rank(history, 0.40)
    assert rank == 1.0
    assert compute_iv_rank(history, 0.30) == 0.0


def test_classify_iv_regime_prefers_rank_over_absolute_level() -> None:
    from pipeline.strategies import classify_iv_regime

    # 50% IV is "moderate" on absolute thresholds but cheap for this name
    assert classify_iv_regime(0.50) == "moderate"
    assert classify_iv_regime(0.50, iv_rank=0.05) == "cheap"
    assert classify_iv_regime(0.50, iv_rank=0.9) == "elevated"
    # Implied-vs-realized fallback when no rank history exists
    assert classify_iv_regime(0.50, realized_vol=0.30) == "elevated"
    assert classify_iv_regime(0.30, realized_vol=0.50) == "cheap"


def test_select_target_expiries_skips_theta_traps() -> None:
    from datetime import date as _date

    from pipeline.options import select_target_expiries

    today = _date(2026, 8, 1)
    expiries = [
        "2026-08-02",  # 1 DTE — skip
        "2026-08-04",  # 3 DTE — skip
        "2026-08-10",  # 9 DTE — front
        "2026-09-04",  # 34 DTE — back
        "2026-10-16",
    ]
    front, back = select_target_expiries(expiries, today=today, min_front_dte=5, min_back_dte=25)
    assert front == "2026-08-10"
    assert back == "2026-09-04"

    # Only short-dated listings: fall back to the furthest available
    front, back = select_target_expiries(
        ["2026-08-02", "2026-08-04"], today=today, min_front_dte=5, min_back_dte=25
    )
    assert front == "2026-08-04"
    assert back is None


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
    kept, dropped = validate_narratives(
        [{"title": "Weak", "tickers": ["ACME"], "sources": [], "options_plays": [{"direction": "call", "ticker": "ACME", "strike_zone": "calls", "expiry": "weekly", "degen_score": 4}]}],
        dossiers,
        require_multi_source=True,
    )
    assert kept == []
    assert len(dropped) == 1
    assert dropped[0]["tickers"] == ["ACME"]
    assert "multi-source bar" in dropped[0]["reason"]

    soft, _ = validate_narratives(
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


def test_evaluate_market_consensus_excludes_best_price_book() -> None:
    """Leave-one-out: the soft book must not vouch for its own number."""
    from pipeline.sports_strategies import evaluate_market

    candidates = evaluate_market(_mispriced_lines(), "h2h", min_books=2)
    best = candidates[0]
    # Sharp books alone imply ~58% for Team A; including the soft book's own
    # quote would drag consensus to ~55% and edge to ~6.4 pts. Edge above 8
    # proves the best-price book was excluded from its benchmark.
    assert best.edge_pct > 8.0
    assert round(best.consensus_probability, 2) == 0.58


def test_evaluate_market_clusters_nearby_total_points() -> None:
    from pipeline.sports_strategies import evaluate_market

    lines = [
        {
            "bookmaker": "Book 1",
            "market": "totals",
            "outcomes": [
                {"name": "Over", "price": -110, "point": 224.5},
                {"name": "Under", "price": -110, "point": 224.5},
            ],
        },
        {
            "bookmaker": "Book 2",
            "market": "totals",
            "outcomes": [
                {"name": "Over", "price": -112, "point": 224.5},
                {"name": "Under", "price": -108, "point": 224.5},
            ],
        },
        {
            "bookmaker": "Book 3",
            "market": "totals",
            "outcomes": [
                {"name": "Over", "price": 100, "point": 225.0},
                {"name": "Under", "price": -120, "point": 225.0},
            ],
        },
    ]
    candidates = evaluate_market(lines, "totals", min_books=3)
    assert candidates, "quotes at 224.5 and 225.0 should pool into one cluster"
    best = candidates[0]
    assert best.book_count == 3
    assert best.mixed_points is True


def test_movement_favors_requires_exact_name_anchor() -> None:
    from pipeline.sports_strategies import _movement_favors

    assert _movement_favors("Over", "Over: +110 -> -105") is True
    assert _movement_favors("Over", "Overtime Kings: +110 -> -105") is False
    assert _movement_favors("Over", "Over: 224.5 (+110) -> 225.5 (-105)") is True


def test_apply_persistence_policy_demotes_first_sighting() -> None:
    from pipeline.sports_strategies import analyze_game, apply_persistence_policy

    now = utc_now()
    decision = analyze_game(
        event_key="evt-persist",
        sport_key="basketball_nba",
        sport_title="NBA",
        home_team="Home",
        away_team="Away",
        commence_time=(now + timedelta(hours=24)).isoformat(),
        line_dicts=_mispriced_lines(),
        now=now,
    )
    assert decision is not None and decision.decision == "bet"

    demoted = apply_persistence_policy(decision, has_recent_prior=False)
    assert demoted.decision == "lean"
    assert demoted.stake_units == 0.0

    fresh = analyze_game(
        event_key="evt-persist",
        sport_key="basketball_nba",
        sport_title="NBA",
        home_team="Home",
        away_team="Away",
        commence_time=(now + timedelta(hours=24)).isoformat(),
        line_dicts=_mispriced_lines(),
        now=now,
    )
    confirmed = apply_persistence_policy(fresh, has_recent_prior=True)
    assert confirmed.decision == "bet"
    assert confirmed.stake_units > 0


def test_analyze_game_rejects_games_already_started() -> None:
    from pipeline.sports_strategies import analyze_game

    now = utc_now()
    decision = analyze_game(
        event_key="evt-live",
        sport_key="basketball_nba",
        sport_title="NBA",
        home_team="Home",
        away_team="Away",
        commence_time=(now - timedelta(hours=1)).isoformat(),
        line_dicts=_mispriced_lines(),
        now=now,
    )
    assert decision is None


def test_grade_outcome_settles_all_markets() -> None:
    from pipeline.sports_grading import grade_outcome

    common = {"home_team": "Home", "away_team": "Away", "home_score": 110, "away_score": 100}
    assert grade_outcome(market="h2h", selection="Home", point=None, **common) == "won"
    assert grade_outcome(market="h2h", selection="Away", point=None, **common) == "lost"
    assert grade_outcome(market="spreads", selection="Away", point=12.5, **common) == "won"
    assert grade_outcome(market="spreads", selection="Away", point=10.0, **common) == "push"
    assert grade_outcome(market="spreads", selection="Home", point=-12.5, **common) == "lost"
    assert grade_outcome(market="totals", selection="Over", point=205.5, **common) == "won"
    assert grade_outcome(market="totals", selection="Under", point=205.5, **common) == "lost"
    assert grade_outcome(market="totals", selection="Over", point=210.0, **common) == "push"


def test_compute_clv_pct_positive_when_beating_close() -> None:
    from pipeline.sports_grading import compute_clv_pct

    # Bet at +105, market closed -110 on the same side: we beat the close.
    assert compute_clv_pct(105, -110) > 0
    # Bet at -120, market closed +100: the market moved against us.
    assert compute_clv_pct(-120, 100) < 0
    assert compute_clv_pct(105, None) is None


def test_compute_record_stats_aggregates_units_and_clv() -> None:
    from pipeline.sports_grading import compute_record_stats

    entries = [
        {"status": "won", "stake_units": 1.0, "best_price": 100, "clv_pct": 2.0},
        {"status": "lost", "stake_units": 2.0, "best_price": -110, "clv_pct": -1.0},
        {"status": "open", "stake_units": 1.5, "best_price": -105, "clv_pct": None},
    ]
    stats = compute_record_stats(entries)
    assert stats["won"] == 1
    assert stats["lost"] == 1
    assert stats["open"] == 1
    assert stats["settled"] == 2
    assert stats["hit_rate"] == 0.5
    # Won 1u at +100 (+1.0), lost 2u (-2.0)
    assert stats["units_pnl"] == -1.0
    assert stats["units_staked"] == 3.0
    assert stats["avg_clv_pct"] == 0.5


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


def test_select_top_tickers_filters_to_universe() -> None:
    counts = {"NVDA": 10, "FOMC": 9, "TLDR": 8, "AMD": 3}
    universe = {"NVDA", "AMD"}
    assert select_top_tickers(counts, limit=3, universe=universe) == ["NVDA", "AMD"]
    # No universe available → no filtering (outage must not blank the watchlist)
    assert select_top_tickers(counts, limit=2, universe=None) == ["NVDA", "FOMC"]


def test_compute_buzz_zscores_uses_trailing_baseline() -> None:
    from pipeline.synthesis import compute_buzz_zscores

    today = {"AAA": 8, "BBB": 3, "CCC": 2}
    history = {
        "AAA": [2, 2, 2, 2, 2, 2, 2],  # steady baseline, today spikes
        "CCC": [2, 2, 2, 2, 2, 2, 2],  # steady baseline, today flat
    }
    z = compute_buzz_zscores(today, history, window_days=7)
    assert z["AAA"] == 6.0
    assert z["BBB"] == 3.0  # brand new ticker vs zero-padded history
    assert z["CCC"] == 0.0
    # A 1→2 blip no longer reads as +100%
    blip = compute_buzz_zscores({"DDD": 2}, {"DDD": [1]}, window_days=7)
    assert blip["DDD"] < 2.0


def test_weighted_ticker_buzz_weighs_engagement_and_dedupes() -> None:
    from pipeline.reddit import RedditPost, weighted_ticker_buzz

    def post(title: str, score: int, comments: int) -> RedditPost:
        return RedditPost(
            subreddit="wallstreetbets",
            title=title,
            selftext="",
            url="https://old.reddit.com/x",
            permalink="/x",
            score=score,
            num_comments=comments,
            created_utc=0.0,
        )

    viral = post("NVDA earnings megathread", 20000, 5000)
    spam = [post(f"BBBY to the moon {i}", 0, 0) for i in range(5)]
    crosspost_a = post("AMD is undervalued!", 10, 2)
    crosspost_b = post("AMD is undervalued!", 10, 2)  # same title, other sub

    scores = weighted_ticker_buzz([viral, *spam, crosspost_a, crosspost_b])
    assert scores["NVDA"] > scores["BBBY"], "one viral thread must outweigh 5 spam posts"
    # crossposts collapse to a single vote
    single = weighted_ticker_buzz([crosspost_a])
    assert scores["AMD"] == single["AMD"]


def test_extract_cashtags_ignores_common_words() -> None:
    from pipeline.tickers import extract_cashtags

    tags = extract_cashtags("Loaded up on $nvda and $AMD, USA YOLO $THE")
    assert tags == {"NVDA", "AMD"}


def test_validate_narratives_replaces_plays_with_offchain_legs() -> None:
    from pipeline.options import OptionsSnapshot
    from pipeline.research import validate_narratives

    expiry = _near_expiry(10)
    snapshot = OptionsSnapshot(
        ticker="ACME",
        current_price=100.0,
        nearest_expiry=expiry,
        chains={expiry: _fake_chain([95.0, 100.0, 105.0])},
    )
    dossiers = [
        {
            "ticker": "ACME",
            "research_quality": {
                "independent_source_count": 2,
                "distinct_domains": ["reuters.com", "cnbc.com"],
                "source_types": ["news"],
                "corroborated_claim_count": 1,
                "meets_multi_source_bar": True,
                "news_domain_count": 2,
            },
            "sources": [],
            "strategy_candidates": [
                {
                    "ticker": "ACME",
                    "direction": "bullish",
                    "strategy_type": "debit_call_spread",
                    "structure": "Buy 100C / Sell 105C",
                    "strike_zone": "$100/$105",
                    "expiry": expiry,
                    "legs": [],
                    "degen_score": 2,
                }
            ],
        }
    ]
    hallucinated = {
        "title": "ACME breakout",
        "tickers": ["ACME"],
        "sources": [],
        "options_plays": [
            {
                "ticker": "ACME",
                "strategy_type": "debit_call_spread",
                "direction": "bullish",
                "degen_score": 2,
                "legs": [
                    # Strike 137 does not exist in the chain
                    {"action": "buy", "option_type": "call", "strike": "137", "expiry": expiry},
                ],
            }
        ],
    }
    kept, _ = validate_narratives(
        [hallucinated], dossiers, require_multi_source=False, options=[snapshot]
    )
    plays = kept[0]["options_plays"]
    assert plays and plays[0]["strategy_type"] == "debit_call_spread"
    assert plays[0]["structure"] == "Buy 100C / Sell 105C", "off-chain play must be replaced"


def test_run_report_builder_headlines() -> None:
    from datetime import date as date_cls

    from pipeline.report import RunReportBuilder

    # Sunday 2026-08-02 — weekend note should appear on empty days
    builder = RunReportBuilder(date_cls(2026, 8, 2))
    builder.stage("reddit_collected", finance_posts=10)
    builder.set(
        "dossier_verdicts",
        [
            {"ticker": "NVDA", "meets_multi_source_bar": False, "fail_reason": "Only Reddit"},
            {"ticker": "TSLA", "meets_multi_source_bar": False, "fail_reason": "No sources"},
        ],
    )
    builder.set("narratives_dropped", [{"title": "Weak", "tickers": ["NVDA"], "reason": "bar"}])
    empty_headline = builder.headline_for("empty", 0)
    assert empty_headline.startswith("0 narratives")
    assert "weekend" in empty_headline
    assert "0/2 dossiers" in empty_headline

    builder.set(
        "dossier_verdicts",
        [{"ticker": "NVDA", "meets_multi_source_bar": True, "fail_reason": ""}],
    )
    success_headline = builder.headline_for("success", 2)
    assert "2 narratives" in success_headline
    assert "NVDA" in success_headline

    failed_headline = builder.headline_for("failed", 0, error="boom")
    assert "reddit_collected" in failed_headline
    assert "boom" in failed_headline

    report = builder.build()
    assert report["stages"][0]["stage"] == "reddit_collected"
    assert "dossier_verdicts" in report


def test_llm_tuning_params_by_model_family() -> None:
    from pipeline.llm import chat_tuning, is_reasoning_model, responses_tuning

    assert is_reasoning_model("gpt-5.6")
    assert is_reasoning_model("gpt-5.6-luna")
    assert not is_reasoning_model("gpt-4o")

    legacy = chat_tuning("gpt-4o", temperature=0.4, max_tokens=2000)
    assert legacy == {"temperature": 0.4, "max_tokens": 2000}
    modern = chat_tuning("gpt-5.6-luna", temperature=0.4, max_tokens=2000)
    assert modern == {"max_completion_tokens": 2000}

    assert responses_tuning("gpt-4o", temperature=0.45, reasoning_effort="medium") == {
        "temperature": 0.45
    }
    assert responses_tuning("gpt-5.6", temperature=0.45, reasoning_effort="medium") == {
        "reasoning": {"effort": "medium"}
    }


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
