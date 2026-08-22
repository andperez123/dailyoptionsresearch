#!/usr/bin/env python3
"""Backfill daily briefings for past dates.

Usage:
    python3 backfill.py --days 7                    # last 7 calendar days
    python3 backfill.py --start 2026-08-15 --end 2026-08-21
    python3 backfill.py --days 7 --export-dir ../reports --force

Historical constraints (stated in each report's metadata rather than papered
over): Reddit hot feeds and yfinance options chains are live-only, so
backfilled reports have no Reddit buzz and no options-chain strategy legs.
News is date-scoped via Google News `after:`/`before:` query operators, movers
and the index tape come from historical prices, and anything published after
the target date is filtered out to avoid look-ahead leakage.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from database import get_briefing_by_date, init_db, save_briefing, save_run_report
from pipeline.candidates import (
    CORE_LIQUID_TICKERS,
    fetch_day_movers,
    fetch_earnings_candidates,
    merge_candidates,
)
from pipeline.dashboard import build_market_dashboard
from pipeline.markdown import briefing_to_markdown
from pipeline.news import collect_news
from pipeline.report import RunReportBuilder
from pipeline.research import build_ticker_dossiers
from pipeline.synthesis import synthesize_briefing
from pipeline.universe import get_ticker_names, get_ticker_universe
from time_utils import parse_rss_datetime


def _end_of_day(day: date) -> datetime:
    return datetime.combine(day, dt_time(23, 59), tzinfo=timezone.utc)


def _published_before(published: str, cutoff: datetime) -> bool:
    if not published:
        return False  # undated items can't be placed in time — exclude
    try:
        dt = parse_rss_datetime(published)
    except Exception:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt <= cutoff


async def backfill_day(day: date, export_dir: Path | None, force: bool) -> str:
    existing = await get_briefing_by_date(day)
    if existing and not force:
        if export_dir:
            path = export_dir / f"{day.isoformat()}.md"
            path.write_text(briefing_to_markdown(day, existing.content))
            return f"{day}: already in DB — exported to {path.name}"
        return f"{day}: already in DB (use --force to regenerate)"

    report = RunReportBuilder(day)
    cutoff = _end_of_day(day)

    universe = await get_ticker_universe()
    names = await get_ticker_names()

    movers, earnings = await asyncio.gather(
        fetch_day_movers(as_of=day),
        fetch_earnings_candidates(as_of=day, days=5),
    )
    candidates = merge_candidates(
        buzz_scores={},  # Reddit history is not retrievable
        movers=movers,
        earnings=earnings,
        catalyst_counts={},
        universe=universe,
    )
    watchlist = candidates.tickers
    candidate_sources = dict(candidates.sources_by_ticker)
    if not watchlist:
        # Every historical source failed (blocked price feeds, no earnings
        # key) — research the most liquid core names rather than nothing.
        watchlist = CORE_LIQUID_TICKERS[:12]
        candidate_sources = {t: ["core_fallback"] for t in watchlist}
    report.stage(
        "watchlist",
        watchlist=watchlist,
        candidate_sources=candidate_sources,
        candidate_details=candidates.details,
        backfill=True,
    )

    # Date-scoped news: a 3-day lookback window ending on the target date.
    news = await collect_news(
        watchlist,
        names=names,
        date_from=day - timedelta(days=2),
        date_to=day + timedelta(days=1),
    )
    # Drop anything published after the target date (live market feeds and
    # imprecise date operators both leak current items into the window).
    news = [item for item in news if _published_before(item.published, cutoff)]
    report.stage("market_data", news_items=len(news), backfill=True)

    dossiers = build_ticker_dossiers(
        tickers=watchlist,
        news=news,
        finance_posts=[],
        options=[],  # options chains are live-only
        overnight_catalysts=[],
        ticker_counts={},
        buzz_deltas={},
        max_age_hours=72,
        ticker_names=names,
        now=cutoff,
        candidate_sources=candidate_sources,
    )
    report.stage("dossiers", built=len(dossiers))

    dashboard = await build_market_dashboard(
        options=[], earnings=earnings, as_of=day
    )
    # The dashboard normally derives movers from options snapshots; use the
    # historical price screen instead.
    dashboard["watchlist_movers"] = [
        {"ticker": t, "price": None, "pct_change": pct} for t, pct in movers[:6]
    ]

    briefing = await synthesize_briefing(
        finance_posts=[],
        sports_posts=[],
        news=news,
        options=[],
        odds=[],
        ticker_counts={},
        buzz_deltas={},
        top_tickers=watchlist,
        dossiers=dossiers,
        ongoing_narratives=[],
        market_dashboard=dashboard,
        report=report,
    )
    briefing.research_metadata["backfill"] = True
    briefing.research_metadata["backfill_limitations"] = (
        "No Reddit buzz (live-only), no options chains (live-only); "
        "news date-scoped via Google News after/before operators"
    )
    report.stage(
        "synthesis", narratives=len(briefing.narratives), radar=len(briefing.radar)
    )

    await save_briefing(day, briefing)
    status = "success" if briefing.narratives else "empty"
    report.set("backfill", True)
    report.set("summary", briefing.summary)
    await save_run_report(
        day,
        report.started_at,
        status,
        f"[backfill] {report.headline_for(status, len(briefing.narratives))}",
        report.build(),
    )

    exported = ""
    if export_dir:
        path = export_dir / f"{day.isoformat()}.md"
        path.write_text(briefing_to_markdown(day, briefing))
        exported = f" — exported to {path.name}"
    return (
        f"{day}: {status}, {len(briefing.narratives)} narratives, "
        f"{len(news)} news items, watchlist {len(watchlist)}{exported}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill daily briefings for past dates")
    parser.add_argument("--start", type=date.fromisoformat, help="First date (inclusive)")
    parser.add_argument("--end", type=date.fromisoformat, help="Last date (inclusive)")
    parser.add_argument("--days", type=int, default=7, help="Backfill the last N days (default 7)")
    parser.add_argument("--export-dir", type=Path, help="Directory for markdown exports")
    parser.add_argument("--force", action="store_true", help="Regenerate existing briefings")
    parser.add_argument(
        "--include-weekends", action="store_true", help="Also generate weekend reports"
    )
    args = parser.parse_args()

    end = args.end or (date.today() - timedelta(days=1))
    start = args.start or (end - timedelta(days=args.days - 1))
    if start > end:
        parser.error("--start must be on or before --end")

    if args.export_dir:
        args.export_dir.mkdir(parents=True, exist_ok=True)

    await init_db()
    day = start
    while day <= end:
        if day.weekday() >= 5 and not args.include_weekends:
            print(f"{day}: weekend — skipped")
        else:
            try:
                print(await backfill_day(day, args.export_dir, args.force))
            except Exception as exc:  # noqa: BLE001 — keep going, report at the end
                print(f"{day}: FAILED — {exc}")
        day += timedelta(days=1)


if __name__ == "__main__":
    asyncio.run(main())
