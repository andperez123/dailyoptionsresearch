from __future__ import annotations

import pytest

from database import _parse_dt
from pipeline.catalyst import _match_ai_results, cluster_key_for
from pipeline.finnhub import NormalizedHeadline
from pipeline.synthesis import select_top_tickers
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
