#!/usr/bin/env python3
"""Dedicated background worker for catalyst intelligence jobs."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from database import cleanup_old_data, init_db, save_market_snapshot, set_pipeline_state
from pipeline.catalyst import run_calendar_sync, run_catalyst_scan
from pipeline.market_data import collect_pulse_snapshots, market_status_now
from pipeline.run import run_pipeline
from pipeline.sports import build_sports_board
from time_utils import utc_now_iso

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("worker")

_shutdown_event = asyncio.Event()


def _request_shutdown() -> None:
    _shutdown_event.set()


async def job_news_scan() -> None:
    logger.info("Starting catalyst news scan")
    try:
        result = await run_catalyst_scan()
        await set_pipeline_state("last_catalyst_scan", utc_now_iso())
        await set_pipeline_state("last_catalyst_result", str(result))
        logger.info("Catalyst scan complete: %s", result)
    except Exception as exc:
        logger.exception("Catalyst scan failed: %s", exc)
        await set_pipeline_state("last_catalyst_error", str(exc))


async def job_market_snapshots() -> None:
    status = market_status_now()
    if status not in ("open", "pre_market"):
        logger.info("Market closed (%s), skipping snapshots", status)
        return
    logger.info("Collecting market snapshots")
    snapshots = await collect_pulse_snapshots()
    for snap in snapshots:
        await save_market_snapshot(snap)
    await set_pipeline_state("last_market_scan", utc_now_iso())


async def job_calendar_sync() -> None:
    logger.info("Syncing earnings calendar")
    count = await run_calendar_sync()
    await set_pipeline_state("last_calendar_sync", utc_now_iso())
    logger.info("Calendar sync saved %s events", count)


async def job_sports_odds() -> None:
    logger.info("Refreshing sports odds")
    board = await build_sports_board(force=True)
    await set_pipeline_state("last_sports_scan", utc_now_iso())
    logger.info("Sports board: %s games", len(board.games))


async def job_daily_briefing() -> None:
    logger.info("Running daily briefing")
    try:
        await run_pipeline()
    except RuntimeError as exc:
        logger.info("Daily briefing skipped: %s", exc)


async def job_cleanup() -> None:
    logger.info("Running daily cleanup")
    await cleanup_old_data(days=30)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    job_defaults = {
        "max_instances": 1,
        "coalesce": True,
        "misfire_grace_time": 60,
    }
    scheduler.add_job(
        job_news_scan,
        IntervalTrigger(minutes=settings.news_scan_interval_minutes),
        id="news_scan",
        replace_existing=True,
        **job_defaults,
    )
    scheduler.add_job(
        job_market_snapshots,
        IntervalTrigger(minutes=settings.market_scan_interval_minutes),
        id="market_snapshots",
        replace_existing=True,
        **job_defaults,
    )
    scheduler.add_job(
        job_calendar_sync,
        IntervalTrigger(hours=settings.calendar_scan_interval_hours),
        id="calendar_sync",
        replace_existing=True,
        **job_defaults,
    )
    scheduler.add_job(
        job_sports_odds,
        IntervalTrigger(minutes=settings.sports_scan_interval_minutes),
        id="sports_odds",
        replace_existing=True,
        **job_defaults,
    )
    scheduler.add_job(
        job_daily_briefing,
        CronTrigger(hour=settings.daily_briefing_hour, minute=0),
        id="daily_briefing",
        replace_existing=True,
        **job_defaults,
    )
    scheduler.add_job(
        job_cleanup,
        CronTrigger(hour=3, minute=0),
        id="cleanup",
        replace_existing=True,
        **job_defaults,
    )
    return scheduler


async def main() -> None:
    await init_db()
    scheduler = create_scheduler()
    scheduler.start()
    logger.info(
        "Worker started — news every %sm, market every %sm",
        settings.news_scan_interval_minutes,
        settings.market_scan_interval_minutes,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _request_shutdown())

    await job_news_scan()
    await job_market_snapshots()

    await _shutdown_event.wait()
    scheduler.shutdown(wait=True)
    logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
