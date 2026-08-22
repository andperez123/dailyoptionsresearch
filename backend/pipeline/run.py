from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from config import settings
from database import (
    add_thread_observation,
    get_atm_iv_history,
    get_ticker_mention_history,
    get_top_catalysts_since,
    list_narrative_threads,
    mark_stale_threads,
    save_briefing,
    save_iv_observations,
    save_run_report,
    save_ticker_mentions,
    set_pipeline_state,
    upsert_narrative_thread,
)
from locks import LOCK_BRIEFING, job_lock
from models import BriefingContent, NarrativeThread
from pipeline.candidates import fetch_earnings_candidates, gather_candidates
from pipeline.dashboard import build_market_dashboard
from pipeline.macro import fetch_macro_snapshot
from pipeline.news import collect_finance_news_for_watchlist
from pipeline.odds import collect_sports_odds
from pipeline.options import collect_options, OptionsSnapshot
from pipeline.reddit import collect_reddit_posts, count_ticker_mentions, weighted_ticker_buzz
from pipeline.report import RunReportBuilder
from pipeline.research import build_ticker_dossiers
from pipeline.sports_news import attach_news_to_events, collect_sports_news, feed_keys_for_sport
from pipeline.sports_strategies import analyze_raw_events, finalize_decisions
from pipeline.strategies import classify_iv_regime, compute_iv_rank
from pipeline.synthesis import (
    compute_buzz_zscores,
    serialize_threads,
    synthesize_briefing,
)
from pipeline.odds import fetch_raw_odds_events
from pipeline.universe import get_ticker_names, get_ticker_universe
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


_THREAD_UPDATE_TYPES = {"new", "continuing", "strengthening", "weakening", "resolved"}


def _quiet_day_note(dossier: dict[str, Any] | None) -> str:
    if dossier is None:
        return "Not in today's watchlist — no fresh signals collected"
    quality = dossier.get("research_quality") or {}
    opts = dossier.get("options") or {}
    parts: list[str] = ["No new corroborated narrative today"]
    mentions = dossier.get("mention_count", 0)
    buzz = dossier.get("buzz_delta", 0.0)
    parts.append(f"buzz z {buzz:+.1f} on {mentions} mention(s)")
    if opts.get("pct_change") is not None:
        parts.append(f"price {opts['pct_change']:+.1f}%")
    if opts.get("iv_rank") is not None:
        parts.append(f"IV rank {round(opts['iv_rank'])}")
    src = quality.get("independent_source_count", 0)
    parts.append(f"{src} independent source(s)")
    return " · ".join(parts)


async def _update_narrative_threads(
    briefing: BriefingContent,
    dossiers: list[dict[str, Any]],
    briefing_date: date,
    threads_before: list[NarrativeThread],
) -> dict[str, Any]:
    """Carry per-ticker storylines forward: upsert threads from today's
    narratives, log quiet-day observations for tracked tickers that produced
    nothing, and stale out threads that have gone dark."""
    existing = {t.ticker: t for t in threads_before}
    updated: set[str] = set()

    for narrative in briefing.narratives:
        tu = narrative.thread_update or {}
        status = str(tu.get("status") or "").lower()
        direction = ""
        if narrative.options_plays:
            direction = narrative.options_plays[0].direction
        for ticker in narrative.tickers:
            t = ticker.upper()
            update_type = status if status in _THREAD_UPDATE_TYPES else (
                "continuing" if t in existing else "new"
            )
            note = (
                str(tu.get("what_changed") or "").strip()
                or narrative.why_now
                or narrative.story[:280]
            )
            await upsert_narrative_thread(
                t,
                update_date=briefing_date,
                title=narrative.title,
                thesis=narrative.insight or narrative.story,
                direction=direction,
                conviction=narrative.degen_score,
                update_type=update_type,
                note=note,
                evidence={
                    "sources": [s.url for s in narrative.sources[:5]],
                    "catalysts": narrative.catalysts[:4],
                    "degen_score": narrative.degen_score,
                },
            )
            updated.add(t)

    dossier_by_ticker = {d["ticker"]: d for d in dossiers}
    quiet = 0
    for ticker, thread in existing.items():
        if thread.status != "active" or ticker in updated:
            continue
        dossier = dossier_by_ticker.get(ticker)
        evidence: dict[str, Any] = {}
        if dossier:
            evidence = {
                "mention_count": dossier.get("mention_count", 0),
                "buzz_delta": dossier.get("buzz_delta", 0.0),
                "options": dossier.get("options") or {},
                "independent_source_count": (dossier.get("research_quality") or {}).get(
                    "independent_source_count", 0
                ),
            }
        await add_thread_observation(
            ticker,
            update_date=briefing_date,
            note=_quiet_day_note(dossier),
            evidence=evidence,
        )
        quiet += 1

    staled = await mark_stale_threads(briefing_date, settings.thread_stale_days)
    return {
        "threads_updated": sorted(updated),
        "quiet_day_observations": quiet,
        "threads_staled": staled,
    }


async def run_pipeline(briefing_date: date | None = None) -> BriefingContent:
    briefing_date = briefing_date or date.today()
    report = RunReportBuilder(briefing_date)
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
            report.stage(
                "reddit_collected",
                finance_posts=len(finance_posts),
                sports_posts=len(sports_posts),
                finance_subreddits=settings.finance_subreddits,
            )

            all_finance_posts = finance_posts
            ticker_counts = count_ticker_mentions(all_finance_posts)
            await save_ticker_mentions(briefing_date, ticker_counts)

            mention_history = await get_ticker_mention_history(
                briefing_date, days=settings.buzz_baseline_days
            )
            buzz_deltas = compute_buzz_zscores(ticker_counts, mention_history)
            report.stage(
                "ticker_buzz",
                tickers_mentioned=len(ticker_counts),
                top_mentions=dict(
                    sorted(ticker_counts.items(), key=lambda kv: -kv[1])[:15]
                ),
            )

            # Overnight catalysts feed both candidate selection and dossiers
            since = utc_now() - timedelta(hours=18)
            catalysts = await get_top_catalysts_since(since, limit=15)
            overnight = [c.model_dump(mode="json") for c in catalysts]
            report.stage("overnight_catalysts", count=len(overnight))

            # Watchlist: Reddit buzz merged with day movers, upcoming earnings,
            # and catalyst-wire tickers — one dead source no longer blanks the
            # list. Active narrative threads are force-included so tracked
            # storylines keep getting research even when their buzz fades.
            universe = await get_ticker_universe()
            buzz_scores = weighted_ticker_buzz(all_finance_posts)
            candidates = await gather_candidates(
                buzz_scores=buzz_scores,
                overnight_catalysts=overnight,
                universe=universe,
                as_of=briefing_date if briefing_date != date.today() else None,
            )
            top_tickers = list(candidates.tickers)

            active_threads = await list_narrative_threads(status="active")
            thread_tickers = [t.ticker for t in active_threads[: settings.thread_max_tracked]]
            forced = [t for t in thread_tickers if t not in top_tickers]
            top_tickers = top_tickers + forced
            candidate_sources = dict(candidates.sources_by_ticker)
            for ticker in forced:
                candidate_sources[ticker] = ["thread"]
            report.stage(
                "watchlist",
                watchlist=top_tickers,
                candidate_sources=candidate_sources,
                candidate_details=candidates.details,
                forced_from_threads=forced,
                active_threads=len(active_threads),
                universe_available=universe is not None,
            )

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
            report.stage(
                "sports",
                odds_events=len(raw_events),
                sports_news=len(sports_news_items),
                bet_decisions=len(sports_bet_decisions),
            )

            ticker_names = await get_ticker_names()
            news, options, odds, macro_context = await asyncio.gather(
                collect_finance_news_for_watchlist(top_tickers, names=ticker_names),
                collect_options(top_tickers),
                collect_sports_odds(limit=12),
                fetch_macro_snapshot(),
            )
            await _attach_iv_rank(options, briefing_date)
            report.stage(
                "market_data",
                news_items=len(news),
                options_snapshots=len(options),
                options_errors=[
                    {"ticker": o.ticker, "error": o.error} for o in options if o.error
                ],
                macro_series=len(macro_context or []),
            )

            dossiers = build_ticker_dossiers(
                tickers=top_tickers,
                news=news,
                finance_posts=all_finance_posts,
                options=options,
                overnight_catalysts=overnight,
                ticker_counts=ticker_counts,
                buzz_deltas=buzz_deltas,
                macro_context=macro_context,
                max_age_hours=settings.briefing_news_max_age_hours,
                ticker_names=ticker_names,
                candidate_sources=candidate_sources,
            )
            report.stage("dossiers", built=len(dossiers))

            earnings_ahead = await fetch_earnings_candidates(days=5, limit=8)
            market_dashboard = await build_market_dashboard(
                options=options,
                earnings=earnings_ahead,
                buzz_deltas=buzz_deltas,
                ticker_counts=ticker_counts,
            )
            report.stage(
                "dashboard",
                indices=len(market_dashboard.get("indices", [])),
                movers=len(market_dashboard.get("watchlist_movers", [])),
            )

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
                dossiers=dossiers,
                ongoing_narratives=serialize_threads(active_threads),
                market_dashboard=market_dashboard,
                report=report,
            )
            report.stage(
                "synthesis",
                narratives=len(briefing.narratives),
                sports_angles=len(briefing.sports_angles),
                radar=len(briefing.radar),
            )

            await save_briefing(briefing_date, briefing)

            thread_summary = await _update_narrative_threads(
                briefing, dossiers, briefing_date, active_threads
            )
            report.stage("threads", **thread_summary)
            report.set("summary", briefing.summary)

            status = "success" if briefing.narratives else "empty"
            headline = report.headline_for(status, len(briefing.narratives))
            await save_run_report(
                briefing_date, report.started_at, status, headline, report.build()
            )

            await set_pipeline_state("last_run", briefing.generated_at.isoformat())
            await set_pipeline_state("message", headline)
            return briefing
        except Exception as exc:  # noqa: BLE001
            await set_pipeline_state("last_error", str(exc))
            try:
                headline = report.headline_for("failed", 0, error=str(exc))
                await save_run_report(
                    briefing_date, report.started_at, "failed", headline, report.build(), error=str(exc)
                )
            except Exception:  # noqa: BLE001 — never mask the original failure
                pass
            raise
        finally:
            await set_pipeline_state("running", "false")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
