from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import date, timedelta
from typing import Any, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError, field_validator

from config import settings
from database import (
    get_recent_catalysts_for_ticker,
    headline_exists,
    insert_raw_headline,
    list_calendar_events,
    save_calendar_events,
    set_deep_dive_cache,
    upsert_cluster,
    upsert_scored_catalyst,
)
from locks import LOCK_CATALYST_SCAN, job_lock
from models import CalendarEvent, DeepDiveResponse
from pipeline.finnhub import NormalizedHeadline, finnhub_client
from pipeline.market_data import collect_ticker_snapshot, fetch_snapshot
from pipeline.news import collect_news
from pipeline.options import fetch_options_snapshot
from pipeline.reddit import collect_reddit_posts, count_ticker_mentions
from pipeline.tickers import extract_tickers
from time_utils import parse_rss_datetime, utc_now, utc_now_iso

logger = logging.getLogger(__name__)


def content_hash(headline: str, url: str) -> str:
    raw = f"{headline.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def cluster_key_for(headline: str, ticker: Optional[str]) -> str:
    words = re.sub(r"[^a-zA-Z0-9 ]", "", headline.lower()).split()
    key_words = " ".join(sorted(set(words))[:6])
    return hashlib.md5(f"{ticker or 'none'}:{key_words}".encode()).hexdigest()


def _normalize_headline(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


class AICatalystScore(BaseModel):
    headline: str
    summary: str = ""
    primary_ticker: Optional[str] = None
    related_tickers: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    direction: str = "neutral"
    catalyst_type: str = "other"
    impact_score: int = 0
    confidence_score: int = 0
    novelty_score: int = 0
    current_market_reaction: Optional[str] = None
    thesis: str = ""
    confirmation_signals: list[str] = Field(default_factory=list)
    invalidation_signals: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    strategy_classification: str = "event_watchlist"
    half_life: str = "intraday"

    @field_validator("impact_score", "confidence_score", "novelty_score")
    @classmethod
    def clamp_scores(cls, value: int) -> int:
        return max(0, min(10, value))


def _match_ai_results(
    items: list[tuple[NormalizedHeadline, dict[str, Any], dict[str, int]]],
    ai_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_headline: dict[str, dict[str, Any]] = {}
    for raw in ai_results:
        try:
            parsed = AICatalystScore.model_validate(raw)
            by_headline[_normalize_headline(parsed.headline)] = parsed.model_dump()
        except ValidationError as exc:
            logger.warning("Skipping invalid AI catalyst row: %s", exc)

    matched: list[dict[str, Any]] = []
    for headline, _, _ in items:
        matched.append(by_headline.get(_normalize_headline(headline.headline), {}))
    return matched


async def ingest_headlines() -> list[NormalizedHeadline]:
    headlines: list[NormalizedHeadline] = []

    if finnhub_client.enabled:
        headlines.extend(await finnhub_client.fetch_general_news(limit=40))

    rss_items = await collect_news([])
    for item in rss_items[:30]:
        tickers = extract_tickers(item.title)
        headlines.append(
            NormalizedHeadline(
                provider="rss",
                external_id=item.url or item.title,
                headline=item.title,
                summary=item.title,
                url=item.url,
                published_at=parse_rss_datetime(item.published),
                related_tickers=tickers[:3],
                raw_payload={"source": item.source, "ticker": item.ticker},
            )
        )

    return headlines


async def store_new_headlines(headlines: list[NormalizedHeadline]) -> list[NormalizedHeadline]:
    new_items: list[NormalizedHeadline] = []
    for h in headlines:
        h_hash = content_hash(h.headline, h.url)
        if await headline_exists(h_hash):
            continue
        row_id = await insert_raw_headline(
            provider=h.provider,
            external_id=h.external_id,
            headline=h.headline,
            summary=h.summary,
            url=h.url,
            published_at=h.published_at,
            content_hash=h_hash,
            raw_payload=h.raw_payload,
        )
        if row_id:
            new_items.append(h)
    return new_items


def rules_baseline_scores(headline: NormalizedHeadline, market: dict[str, Any]) -> dict[str, int]:
    impact = 4
    confidence = 3
    novelty = 5
    if headline.provider == "finnhub":
        confidence += 1
    tickers = headline.related_tickers or extract_tickers(headline.headline)
    if tickers:
        impact += 1
    pct = market.get("pct_change")
    if pct is not None and abs(pct) >= 2:
        impact += 2
        confidence += 1
    rel_vol = market.get("relative_volume")
    if rel_vol and rel_vol >= 1.5:
        confidence += 1
    return {
        "impact_score": min(impact, 10),
        "confidence_score": min(confidence, 10),
        "novelty_score": min(novelty, 10),
    }


SCORING_PROMPT = """You are a market catalyst analyst. Score news into structured catalyst signals.
Separate observations from trade ideas. Do NOT recommend exact strikes unless liquidity is confirmed.
Return JSON object with a "results" array containing one object per headline.
Each object MUST include the exact input headline string in the "headline" field."""


async def ai_score_headlines(
    items: list[tuple[NormalizedHeadline, dict[str, Any], dict[str, int]]],
) -> list[dict[str, Any]]:
    if not settings.openai_api_key or not items:
        return []

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    payload = []
    for headline, market, baseline in items:
        payload.append(
            {
                "headline": headline.headline,
                "summary": headline.summary,
                "source": headline.provider,
                "tickers": headline.related_tickers or extract_tickers(headline.headline),
                "market_reaction": market,
                "baseline_scores": baseline,
            }
        )

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model_mini,
            messages=[
                {"role": "system", "content": SCORING_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "headlines": payload,
                            "schema": {
                                "results": [
                                    {
                                        "headline": "string (must match input)",
                                        "summary": "string",
                                        "primary_ticker": "string|null",
                                        "related_tickers": ["TICK"],
                                        "sectors": ["string"],
                                        "direction": "bullish|bearish|mixed|volatility|neutral",
                                        "catalyst_type": "earnings|guidance|analyst_action|regulatory|product|management|macro|merger|legal|social_momentum|other",
                                        "impact_score": "1-10",
                                        "confidence_score": "1-10",
                                        "novelty_score": "1-10",
                                        "current_market_reaction": "string",
                                        "thesis": "string",
                                        "confirmation_signals": ["string"],
                                        "invalidation_signals": ["string"],
                                        "key_risks": ["string"],
                                        "strategy_classification": "directional_calls|directional_puts|debit_spread|credit_spread|volatility_expansion|volatility_contraction|event_watchlist|no_trade",
                                        "half_life": "intraday|1-3_days|1-2_weeks|longer_term",
                                    }
                                ]
                            },
                        }
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=4000,
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        results = data.get("results") or data.get("headlines") or data.get("catalysts") or []
        if isinstance(results, dict):
            results = [results]
        return results if isinstance(results, list) else []
    except Exception as exc:
        logger.error("AI scoring failed: %s", exc)
        return []


async def process_catalyst_batch(headlines: list[NormalizedHeadline]) -> int:
    if not headlines:
        return 0

    enriched: list[tuple[NormalizedHeadline, dict[str, Any], dict[str, int]]] = []
    for h in headlines[:15]:
        tickers = h.related_tickers or extract_tickers(h.headline)
        primary = tickers[0] if tickers else None
        market: dict[str, Any] = {}
        if primary:
            snap = await collect_ticker_snapshot(primary)
            market = {
                "price": snap.price,
                "pct_change": snap.pct_change,
                "relative_volume": snap.relative_volume,
                "implied_volatility": snap.implied_volatility,
            }
        baseline = rules_baseline_scores(h, market)
        enriched.append((h, market, baseline))

    ai_results = _match_ai_results(enriched, await ai_score_headlines(enriched))
    saved = 0
    now = utc_now_iso()

    for (headline, market, baseline), ai in zip(enriched, ai_results):
        tickers = headline.related_tickers or extract_tickers(headline.headline)
        primary = tickers[0] if tickers else None

        cluster_id, source_count = await upsert_cluster(
            cluster_key=cluster_key_for(headline.headline, primary),
            canonical_title=headline.headline,
            primary_ticker=primary,
        )

        reaction_parts = []
        if market.get("pct_change") is not None:
            reaction_parts.append(f"Price {market['pct_change']:+.2f}%")
        if market.get("relative_volume"):
            reaction_parts.append(f"Rel vol {market['relative_volume']}x")
        if market.get("implied_volatility"):
            reaction_parts.append(f"Avg IV {market['implied_volatility']:.2%}")

        catalyst = {
            "cluster_id": cluster_id,
            "headline": headline.headline,
            "summary": ai.get("summary") or headline.summary,
            "source_name": headline.provider,
            "source_url": headline.url,
            "published_at": headline.published_at.isoformat(),
            "detected_at": now,
            "primary_ticker": ai.get("primary_ticker") or primary,
            "related_tickers": ai.get("related_tickers") or tickers,
            "sectors": ai.get("sectors") or [],
            "direction": ai.get("direction", "neutral"),
            "catalyst_type": ai.get("catalyst_type", "other"),
            "impact_score": ai.get("impact_score", baseline["impact_score"]),
            "confidence_score": ai.get("confidence_score", baseline["confidence_score"]),
            "novelty_score": ai.get("novelty_score", baseline["novelty_score"]),
            "current_market_reaction": ai.get("current_market_reaction")
            or ("; ".join(reaction_parts) if reaction_parts else None),
            "thesis": ai.get("thesis", headline.summary),
            "confirmation_signals": ai.get("confirmation_signals", []),
            "invalidation_signals": ai.get("invalidation_signals", []),
            "key_risks": ai.get("key_risks", []),
            "strategy_classification": ai.get("strategy_classification", "event_watchlist"),
            "half_life": ai.get("half_life", "intraday"),
            "supporting_source_count": source_count,
            "market_reaction_snapshot": market,
            "model_version": settings.catalyst_model_version,
            "scoring_version": settings.catalyst_scoring_version,
            "scored": bool(ai),
        }
        await upsert_scored_catalyst(catalyst)
        saved += 1
    return saved


async def run_catalyst_scan() -> dict[str, Any]:
    async with job_lock(LOCK_CATALYST_SCAN, "catalyst_scan") as acquired:
        if not acquired:
            return {"status": "skipped", "reason": "lock_held"}
        headlines = await ingest_headlines()
        new_headlines = await store_new_headlines(headlines)
        saved = await process_catalyst_batch(new_headlines)
        return {"ingested": len(headlines), "new": len(new_headlines), "scored": saved}


async def run_calendar_sync() -> int:
    if not finnhub_client.enabled:
        return 0
    start = date.today()
    end = start + timedelta(days=7)
    earnings = await finnhub_client.fetch_earnings_calendar(start.isoformat(), end.isoformat())
    events: list[CalendarEvent] = []
    for e in earnings[:50]:
        if not e.ticker:
            continue
        snap = await asyncio.to_thread(fetch_snapshot, e.ticker)
        vol_ctx = None
        if snap.implied_volatility and snap.implied_volatility > 0.5:
            vol_ctx = "elevated"
        elif snap.implied_volatility and snap.implied_volatility < 0.25:
            vol_ctx = "muted"
        events.append(
            CalendarEvent(
                ticker=e.ticker.upper(),
                event_type="earnings",
                title=f"{e.ticker} earnings ({e.hour or 'TBD'})",
                event_date=date.fromisoformat(e.date) if e.date else start,
                iv_level=f"{snap.implied_volatility:.1%}" if snap.implied_volatility else None,
                recent_price_change=snap.pct_change,
                vol_context=vol_ctx,
            )
        )
    await save_calendar_events(events)
    return len(events)


DEEP_DIVE_SCHEMA = {
    "bull_case": "string",
    "bear_case": "string",
    "analysis": "string",
    "confirmation_levels": ["string"],
    "invalidation_levels": ["string"],
}


async def build_deep_dive(ticker: str) -> DeepDiveResponse:
    ticker = ticker.upper()
    now = utc_now()
    cached_until = now + timedelta(minutes=settings.deep_dive_cache_minutes)
    warnings: list[str] = []

    price_snap = await collect_ticker_snapshot(ticker)
    options = await asyncio.to_thread(fetch_options_snapshot, ticker)
    options_data = {
        "nearest_expiry": options.nearest_expiry,
        "avg_iv": options.avg_iv,
        "put_call_volume_ratio": options.put_call_volume_ratio,
        "notable_calls": [
            {"strike": c.strike, "volume": c.volume, "oi": c.open_interest}
            for c in options.notable_calls
        ],
        "notable_puts": [
            {"strike": c.strike, "volume": c.volume, "oi": c.open_interest}
            for c in options.notable_puts
        ],
        "error": options.error,
    }
    if options.error:
        warnings.append("Options data unavailable — strategy details require validation")

    catalysts = await get_recent_catalysts_for_ticker(ticker, limit=8)
    events = await list_calendar_events(days=14, tickers=[ticker])

    posts = await collect_reddit_posts(settings.finance_subreddits[:2], posts_per_sub=8)
    counts = count_ticker_mentions(posts)
    social = {"mention_count": counts.get(ticker, 0), "note": "Social influences confidence only"}

    bull_case = ""
    bear_case = ""
    ai_analysis = ""
    confirmation: list[str] = []
    invalidation: list[str] = []

    if settings.openai_api_key:
        try:
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.chat.completions.create(
                model=settings.openai_model_mini,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Provide factual market analysis. Separate observations from trade ideas. "
                            "No exact strike picks without liquidity confirmation. "
                            "Return JSON matching the provided schema."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "ticker": ticker,
                                "price": price_snap.model_dump(mode="json"),
                                "options": options_data,
                                "recent_catalysts": [c.model_dump(mode="json") for c in catalysts[:5]],
                                "social": social,
                                "schema": DEEP_DIVE_SCHEMA,
                            }
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.4,
                max_tokens=2000,
            )
            parsed = json.loads(response.choices[0].message.content or "{}")
            bull_case = parsed.get("bull_case", "")
            bear_case = parsed.get("bear_case", "")
            ai_analysis = parsed.get("analysis", "")
            confirmation = parsed.get("confirmation_levels", [])
            invalidation = parsed.get("invalidation_levels", [])
        except Exception as exc:
            warnings.append(f"AI analysis unavailable: {exc}")

    payload = DeepDiveResponse(
        ticker=ticker,
        price_snapshot=price_snap,
        options_snapshot=options_data,
        recent_catalysts=catalysts,
        upcoming_events=events,
        social_momentum=social,
        bull_case=bull_case,
        bear_case=bear_case,
        confirmation_levels=confirmation,
        invalidation_levels=invalidation,
        data_quality_warnings=warnings,
        ai_analysis=ai_analysis,
        generated_at=now,
        cached_until=cached_until,
    )
    await set_deep_dive_cache(ticker, payload)
    return payload
