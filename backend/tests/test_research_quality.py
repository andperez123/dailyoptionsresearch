"""Unit tests for the research-quality overhaul: publisher-domain handling,
claim clustering, candidate merging, and company-name cleaning."""

from __future__ import annotations

from time_utils import utc_now


# ---------------------------------------------------------------------------
# Publisher domains
# ---------------------------------------------------------------------------


def test_domain_of_strips_www_and_handles_junk() -> None:
    from pipeline.news import domain_of

    assert domain_of("https://www.reuters.com/markets/story") == "reuters.com"
    assert domain_of("https://news.google.com/rss/articles/abc") == "news.google.com"
    assert domain_of("not a url") == ""


def test_dossier_uses_publisher_domain_not_redirect_host() -> None:
    """Two Google News items (both news.google.com URLs) with distinct real
    publishers must count as two independent domains."""
    from pipeline.news import NewsItem
    from pipeline.research import build_ticker_dossiers

    now_iso = utc_now().isoformat()
    news = [
        NewsItem(
            title="Acme wins major cloud contract deal",
            url="https://news.google.com/rss/articles/aaa",
            source="Reuters",
            published=now_iso,
            ticker="ACME",
            publisher_domain="reuters.com",
        ),
        NewsItem(
            title="Acme wins big cloud contract award",
            url="https://news.google.com/rss/articles/bbb",
            source="CNBC",
            published=now_iso,
            ticker="ACME",
            publisher_domain="cnbc.com",
        ),
    ]
    dossiers = build_ticker_dossiers(
        tickers=["ACME"],
        news=news,
        finance_posts=[],
        options=[],
        overnight_catalysts=[],
        ticker_counts={},
        buzz_deltas={},
        max_age_hours=24,
    )
    quality = dossiers[0]["research_quality"]
    assert quality["news_domain_count"] == 2
    assert quality["meets_multi_source_bar"] is True
    assert quality["conviction_tier"] == "confirmed"
    # And the shared story corroborates via token overlap
    assert quality["corroborated_claim_count"] >= 1


def test_company_name_matching_attaches_news_without_ticker_symbol() -> None:
    from pipeline.news import NewsItem
    from pipeline.research import build_ticker_dossiers

    news = [
        NewsItem(
            title="Acme Robotics lands Pentagon deal",
            url="https://reuters.com/x",
            source="Reuters",
            published=utc_now().isoformat(),
            ticker=None,  # general feed item, no ticker tag
            publisher_domain="reuters.com",
        )
    ]
    dossiers = build_ticker_dossiers(
        tickers=["ACME"],
        news=news,
        finance_posts=[],
        options=[],
        overnight_catalysts=[],
        ticker_counts={},
        buzz_deltas={},
        max_age_hours=24,
        ticker_names={"ACME": "Acme Robotics"},
    )
    assert len(dossiers[0]["sources"]) == 1


def test_common_word_tickers_require_cashtag_or_company_name() -> None:
    """`BY` must not attach to every headline containing the word 'by'."""
    from pipeline.research import _ticker_in_text

    assert not _ticker_in_text("BY", "STOCKS RALLY DRIVEN BY AI OPTIMISM")
    assert _ticker_in_text("BY", "LOADING UP ON $BY CALLS")
    assert _ticker_in_text("BY", "BYLINE BANCORP BEATS ESTIMATES", name="Byline Bancorp")
    # Normal symbols still match as bare words
    assert _ticker_in_text("NVDA", "NVDA EARNINGS TONIGHT")


# ---------------------------------------------------------------------------
# Claim clustering
# ---------------------------------------------------------------------------


def test_cluster_claims_groups_paraphrased_headlines() -> None:
    from pipeline.research import cluster_claims

    entries = [
        {
            "title": "Broadcom seeks more than $60 billion in latest AI debt deal",
            "domain": "bloomberg.com",
            "url": "https://bloomberg.com/1",
            "weight": 1,
        },
        {
            "title": "Broadcom seeks over $60 billion AI debt deal, Bloomberg reports",
            "domain": "reuters.com",
            "url": "https://reuters.com/2",
            "weight": 1,
        },
        {
            "title": "Walmart shares slump on weakest sales growth in years",
            "domain": "wsj.com",
            "url": "https://wsj.com/3",
            "weight": 1,
        },
    ]
    clusters = cluster_claims(entries)
    assert len(clusters) == 1  # only the corroborated Broadcom story qualifies
    assert clusters[0]["domain_count"] == 2
    assert set(clusters[0]["independent_domains"]) == {"bloomberg.com", "reuters.com"}


def test_cluster_claims_requires_overlap_not_exact_match() -> None:
    from pipeline.research import _claim_tokens, _jaccard

    a = _claim_tokens("Broadcom seeks more than $60 billion in latest AI debt deal")
    b = _claim_tokens("Broadcom seeks over $60 billion AI debt deal, Bloomberg reports")
    assert a != b  # exact-key matching (the old approach) would have failed
    assert _jaccard(a, b) >= 0.35


def test_cluster_claims_single_uncorroborated_claim_excluded() -> None:
    from pipeline.research import cluster_claims

    clusters = cluster_claims(
        [{"title": "Unique niche story about a small cap", "domain": "blog.com", "url": "u", "weight": 1}]
    )
    assert clusters == []


# ---------------------------------------------------------------------------
# Candidate merging
# ---------------------------------------------------------------------------


def test_merge_candidates_guarantees_source_diversity() -> None:
    from pipeline.candidates import merge_candidates

    result = merge_candidates(
        buzz_scores={"MEME": 100.0, "YOLO": 90.0, "HYPE": 80.0, "MOON": 70.0, "APES": 60.0},
        movers=[("MOVE", 5.0), ("DROP", -4.0)],
        earnings=[("EARN", "2026-08-25")],
        catalyst_counts={"CATA": 3},
        universe=None,
        limit=8,
    )
    assert "MOVE" in result.tickers and "DROP" in result.tickers
    assert "EARN" in result.tickers
    assert "CATA" in result.tickers
    assert result.sources_by_ticker["MOVE"] == ["movers"]


def test_merge_candidates_filters_by_universe_and_boosts_multi_source() -> None:
    from pipeline.candidates import merge_candidates

    result = merge_candidates(
        buzz_scores={"REAL": 50.0, "FAKE": 100.0},
        movers=[("REAL", 3.0)],
        earnings=[],
        catalyst_counts={},
        universe={"REAL"},
        limit=5,
    )
    assert "FAKE" not in result.tickers
    assert result.tickers[0] == "REAL"
    assert set(result.sources_by_ticker["REAL"]) == {"movers", "reddit"}


def test_merge_candidates_survives_dead_reddit() -> None:
    from pipeline.candidates import merge_candidates

    result = merge_candidates(
        buzz_scores={},
        movers=[("AAA", 6.0), ("BBB", -3.2)],
        earnings=[("CCC", "2026-08-24")],
        catalyst_counts={},
        universe=None,
        limit=15,
    )
    assert result.tickers  # a dead Reddit day no longer blanks the watchlist
    assert {"AAA", "BBB", "CCC"} <= set(result.tickers)


# ---------------------------------------------------------------------------
# Company-name cleaning
# ---------------------------------------------------------------------------


def test_clean_company_name() -> None:
    from pipeline.universe import clean_company_name

    assert clean_company_name("Apple Inc. - Common Stock") == "Apple"
    assert clean_company_name("NVIDIA Corporation - Common Stock") == "NVIDIA"
    assert (
        clean_company_name("Alphabet Inc. - Class A Capital Stock") == "Alphabet"
    )
    assert clean_company_name("AT&T Inc.") == "AT&T"
