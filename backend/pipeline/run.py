from __future__ import annotations

import asyncio
from datetime import date, timedelta

from config import settings
from database import (
    get_ticker_mentions,
    get_top_catalysts_since,
    save_briefing,
    save_ticker_mentions,
    set_pipeline_state,
)
from locks import LOCK_BRIEFING, job_lock
from models import BriefingContent
from pipeline.news import collect_news
from pipeline.odds import collect_sports_odds
from pipeline.options import collect_options
from pipeline.reddit import collect_reddit_posts, count_ticker_mentions
from pipeline.synthesis import compute_buzz_delta, select_top_tickers, synthesize_briefing
from time_utils import utc_now


async def run_pipeline(briefing_date: date | None = None) -> BriefingContent:
    briefing_date = briefing_date or date.today()
    async with job_lock(LOCK_BRIEFING, "briefing") as acquired:
        if not acquired:
            raise RuntimeError("Briefing already running in another process")

        await set_pipeline_state("running", "true")
        await set_pipeline_state("last_error", "")

        try:
            finance_posts, sports_posts, odds = await asyncio.gather(
                collect_reddit_posts(settings.finance_subreddits),
                collect_reddit_posts(settings.sports_subreddits),
                collect_sports_odds(),
            )

            all_finance_posts = finance_posts
            ticker_counts = count_ticker_mentions(all_finance_posts)
            await save_ticker_mentions(briefing_date, ticker_counts)

            yesterday = briefing_date - timedelta(days=1)
            yesterday_counts = await get_ticker_mentions(yesterday)
            buzz_deltas = compute_buzz_delta(ticker_counts, yesterday_counts)
            top_tickers = select_top_tickers(ticker_counts)

            news, options = await asyncio.gather(
                collect_news(top_tickers),
                collect_options(top_tickers),
            )

            since = utc_now() - timedelta(hours=18)
            catalysts = await get_top_catalysts_since(since, limit=15)
            overnight = [c.model_dump(mode="json") for c in catalysts]

            briefing = await synthesize_briefing(
                finance_posts=all_finance_posts,
                sports_posts=sports_posts,
                news=news,
                options=options,
                odds=odds,
                ticker_counts=ticker_counts,
                buzz_deltas=buzz_deltas,
                overnight_catalysts=overnight,
            )

            await save_briefing(briefing_date, briefing)
            await set_pipeline_state("last_run", briefing.generated_at.isoformat())
            await set_pipeline_state("message", f"Briefing saved for {briefing_date.isoformat()}")
            return briefing
        except Exception as exc:  # noqa: BLE001
            await set_pipeline_state("last_error", str(exc))
            raise
        finally:
            await set_pipeline_state("running", "false")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
