"""End-to-end run_pipeline tests with mocked collectors and LLM.

Verifies the two observability guarantees added on top of the briefing:
1. A run report is persisted for every run — success, empty, and failed.
2. Narrative threads carry per-ticker storylines across runs, including
   quiet-day observations when a tracked ticker produces no narrative.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from config import settings
from pipeline.news import NewsItem
from pipeline.options import OptionsSnapshot
from pipeline.reddit import RedditPost
from time_utils import utc_now


def _post(title: str, score: int = 50) -> RedditPost:
    return RedditPost(
        subreddit="stocks",
        title=title,
        selftext="",
        url="https://reddit.com/r/stocks/post",
        permalink="/r/stocks/post",
        score=score,
        num_comments=10,
        created_utc=utc_now().timestamp(),
    )


def _news(url: str, source: str) -> NewsItem:
    return NewsItem(
        title="Acme wins major cloud contract",
        url=url,
        source=source,
        published=utc_now().isoformat(),
        ticker="ACME",
        source_tier="rss",
        summary="Acme secured a multi-year cloud deal.",
    )


NARRATIVE_JSON = {
    "summary": "Acme cloud contract dominates.",
    "narratives": [
        {
            "title": "Acme cloud momentum",
            "tickers": ["ACME"],
            "story": "Two outlets confirm the contract.",
            "why_now": "Contract announced this morning.",
            "insight": "Cross-source: capex guides support follow-through.",
            "priced_in": "Partially.",
            "bull_case": "Backlog grows.",
            "bear_case": "Margins compress.",
            "catalysts": ["Earnings 2026-08-20"],
            "confirmation_points": ["Follow-on orders"],
            "invalidation_points": ["Contract cancellation"],
            "thread_update": {"status": "new", "what_changed": ""},
            "degen_score": 3,
            "options_plays": [],
            "sources": [
                {"title": "Reuters", "url": "https://reuters.com/acme", "source_type": "news"},
                {"title": "CNBC", "url": "https://cnbc.com/acme", "source_type": "news"},
            ],
        }
    ],
    "sports_angles": [],
    "radar": [],
}

EMPTY_JSON = {"summary": "Quiet day.", "narratives": [], "sports_angles": [], "radar": []}


@pytest.fixture
def pipeline_env(tmp_path, monkeypatch):
    """Isolated DB + all external collectors mocked. Returns a dict whose
    'llm_response' key controls what the fake LLM returns per run."""
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    state = {"llm_response": NARRATIVE_JSON}

    import pipeline.run as run_mod
    import pipeline.synthesis as synth_mod

    async def fake_reddit(subreddits):
        if "stocks" in subreddits:
            return [_post("ACME to the moon $ACME"), _post("$ACME contract win")]
        return []

    async def fake_universe():
        return {"ACME"}

    async def fake_news(tickers):
        return [_news("https://reuters.com/acme", "Reuters"), _news("https://cnbc.com/acme", "CNBC")]

    async def fake_options(tickers):
        return [
            OptionsSnapshot(ticker=t, current_price=50.0, nearest_expiry=None, pct_change=1.5)
            for t in tickers
        ]

    async def fake_odds(limit=12):
        return []

    async def fake_raw_odds(per_sport_limit=8):
        return []

    async def fake_sports_news(feed_keys):
        return []

    async def fake_macro():
        return []

    async def fake_llm(client, prompt):
        return json.dumps(state["llm_response"]), [], "responses"

    monkeypatch.setattr(run_mod, "collect_reddit_posts", fake_reddit)
    monkeypatch.setattr(run_mod, "get_ticker_universe", fake_universe)
    monkeypatch.setattr(run_mod, "collect_finance_news_for_watchlist", fake_news)
    monkeypatch.setattr(run_mod, "collect_options", fake_options)
    monkeypatch.setattr(run_mod, "collect_sports_odds", fake_odds)
    monkeypatch.setattr(run_mod, "fetch_raw_odds_events", fake_raw_odds)
    monkeypatch.setattr(run_mod, "collect_sports_news", fake_sports_news)
    monkeypatch.setattr(run_mod, "fetch_macro_snapshot", fake_macro)
    monkeypatch.setattr(synth_mod, "_generate_briefing_json", fake_llm)

    return state


async def test_pipeline_saves_report_and_opens_thread(pipeline_env):
    from database import get_run_report_by_date, get_thread_by_ticker, init_db
    from pipeline.run import run_pipeline

    await init_db()
    day1 = date(2026, 8, 3)
    briefing = await run_pipeline(day1)

    assert len(briefing.narratives) == 1

    report = await get_run_report_by_date(day1)
    assert report is not None
    assert report.status == "success"
    assert "ACME" in report.headline
    stage_names = [s["stage"] for s in report.report["stages"]]
    assert "reddit_collected" in stage_names
    assert "synthesis" in stage_names
    assert "threads" in stage_names
    verdicts = report.report["dossier_verdicts"]
    assert verdicts and verdicts[0]["ticker"] == "ACME"
    assert verdicts[0]["meets_multi_source_bar"] is True

    thread = await get_thread_by_ticker("ACME")
    assert thread is not None
    assert thread.status == "active"
    assert thread.title == "Acme cloud momentum"
    assert thread.updates[0].update_type == "new"


async def test_empty_day_still_reports_and_logs_quiet_observation(pipeline_env):
    from database import get_run_report_by_date, get_thread_by_ticker, init_db
    from pipeline.run import run_pipeline

    await init_db()
    day1 = date(2026, 8, 3)
    await run_pipeline(day1)  # opens the ACME thread

    # Next day the model produces nothing
    pipeline_env["llm_response"] = EMPTY_JSON
    day2 = date(2026, 8, 4)
    briefing = await run_pipeline(day2)

    assert briefing.narratives == []
    report = await get_run_report_by_date(day2)
    assert report is not None
    assert report.status == "empty"
    assert report.headline.startswith("0 narratives")
    # Empty day still explains itself: dossier verdicts are present
    assert report.report["dossier_verdicts"]
    assert report.report["raw_narrative_count"] == 0

    # The tracked ACME thread got a quiet-day observation, not silence
    thread = await get_thread_by_ticker("ACME")
    assert len(thread.updates) == 2
    assert thread.updates[0].update_date == day2
    assert thread.updates[0].update_type == "no_new_evidence"
    assert "buzz" in thread.updates[0].note


async def test_failed_run_persists_partial_report(pipeline_env, monkeypatch):
    from database import get_run_report_by_date, init_db
    from pipeline.run import run_pipeline
    import pipeline.run as run_mod

    await init_db()

    async def boom(tickers):
        raise RuntimeError("options provider down")

    monkeypatch.setattr(run_mod, "collect_options", boom)

    day = date(2026, 8, 5)
    with pytest.raises(RuntimeError, match="options provider down"):
        await run_pipeline(day)

    report = await get_run_report_by_date(day)
    assert report is not None
    assert report.status == "failed"
    assert "options provider down" in (report.error or "")
    # Stages before the failure survived
    stage_names = [s["stage"] for s in report.report["stages"]]
    assert "reddit_collected" in stage_names
    assert "watchlist" in stage_names
    assert "synthesis" not in stage_names


async def test_active_thread_ticker_forced_into_watchlist(pipeline_env):
    from database import get_run_report_by_date, init_db, upsert_narrative_thread
    from pipeline.run import run_pipeline

    await init_db()
    # Track a ticker that has zero buzz today
    await upsert_narrative_thread(
        "QUIET",
        update_date=date(2026, 8, 1),
        title="Quiet thesis",
        thesis="Still developing",
        update_type="new",
        note="opened",
    )

    day = date(2026, 8, 3)
    await run_pipeline(day)

    report = await get_run_report_by_date(day)
    watchlist_stage = next(s for s in report.report["stages"] if s["stage"] == "watchlist")
    assert "QUIET" in watchlist_stage["watchlist"]
    assert "QUIET" in watchlist_stage["forced_from_threads"]
