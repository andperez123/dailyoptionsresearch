from __future__ import annotations

import asyncio
from datetime import date, timedelta

from config import settings
from database import (
    get_atm_iv_history,
    get_ticker_mention_history,
    get_top_catalysts_since,
    save_briefing,
    save_iv_observations,
    save_ticker_mentions,
    set_pipeline_state,
)
from locks import LOCK_BRIEFING, job_lock
from models import BriefingContent
from pipeline.macro import fetch_macro_snapshot
from pipeline.news import collect_finance_news_for_watchlist
from pipeline.odds import collect_sports_odds
from pipeline.options import collect_options, OptionsSnapshot
from pipeline.reddit import collect_reddit_posts, count_ticker_mentions, weighted_ticker_buzz
from pipeline.sports_news import attach_news_to_events, collect_sports_news, feed_keys_for_sport
from pipeline.sports_strategies import analyze_raw_events, finalize_decisions
from pipeline.strategies import classify_iv_regime, compute_iv_rank
from pipeline.synthesis import compute_buzz_zscores, select_top_tickers, synthesize_briefing
from pipeline.odds import fetch_raw_odds_events
from pipeline.universe import get_ticker_universe
from time_utils import utc_now


async def _attach_iv_rank(options: list[OptionsSnapshot], briefing_date: date) -> None:
    """Persist today's ATM IV prints and rank each ticker against its own
    trailing history — absolute IV thresholds misclassify meme names and
    mega-caps alike, so rank (or IV-vs-realized) drives the regime instead."""
    observations = {
        snap.ticker: (snap.atm_iv, snap.realized_vol_20d)
        for snap in options
        if snap.atm_iv is not None
    }
    if observations:
        await save_iv_observations(briefing_date, observations)
    for snap in options:
        if snap.atm_iv is None:
            continue
        history = await get_atm_iv_history(snap.ticker, days=90, before=briefing_date)
        snap.iv_rank = compute_iv_rank(history, snap.atm_iv)
        snap.iv_regime = classify_iv_regime(
            snap.atm_iv,
            iv_rank=snap.iv_rank,
            realized_vol=snap.realized_vol_20d,
        )


async def run_pipeline(briefing_date: date | None = None) -> BriefingContent:
    briefing_date = briefing_date or date.today()
    async with job_lock(LOCK_BRIEFING, "briefing") as acquired:
        if not acquired:
            raise RuntimeError("Briefing already running in another process")

        await set_pipeline_state("running", "true")
        await set_pipeline_state("last_error", "")

        try:
            finance_posts, sports_posts = await asyncio.gather(
                collect_reddit_posts(settings.finance_subreddits),
                collect_reddit_posts(settings.sports_subreddits),
            )

            all_finance_posts = finance_posts
            ticker_counts = count_ticker_mentions(all_finance_posts)
            await save_ticker_mentions(briefing_date, ticker_counts)

            mention_history = await get_ticker_mention_history(
                briefing_date, days=settings.buzz_baseline_days
            )
            buzz_deltas = compute_buzz_zscores(ticker_counts, mention_history)

            # Watchlist: engagement-weighted buzz, restricted to real symbols
            universe = await get_ticker_universe()
            buzz_scores = weighted_ticker_buzz(all_finance_posts)
            top_tickers = select_top_tickers(buzz_scores, universe=universe)

            raw_events = await fetch_raw_odds_events(per_sport_limit=8)
            feed_keys: set[str] = set()
            for event in raw_events:
                feed_keys.update(feed_keys_for_sport(event.get("sport_key", "")))
            sports_news_items = await collect_sports_news(sorted(feed_keys))
            enriched_events, sports_news_counts = attach_news_to_events(raw_events, sports_news_items)
            sports_bet_decisions = await finalize_decisions(
                analyze_raw_events(
                    enriched_events,
                    news_counts=sports_news_counts,
                    now=utc_now(),
                )
            )
            sports_news_payload = [
                {
                    "title": item.title,
                    "url": item.url,
                    "source": item.source,
                    "published": item.published,
                    "feed_key": item.feed_key,
                }
                for item in sports_news_items[:20]
            ]

            news, options, odds, macro_context = await asyncio.gather(
                collect_finance_news_for_watchlist(top_tickers),
                collect_options(top_tickers),
                collect_sports_odds(limit=12),
                fetch_macro_snapshot(),
            )
            await _attach_iv_rank(options, briefing_date)

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
                macro_context=macro_context,
                sports_news=sports_news_payload,
                sports_bet_decisions=sports_bet_decisions,
                top_tickers=top_tickers,
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
