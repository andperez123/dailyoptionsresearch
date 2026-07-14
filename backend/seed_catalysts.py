#!/usr/bin/env python3
"""Seed demo catalyst signals for UI testing."""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import init_db, insert_scored_catalyst, upsert_cluster


async def seed_catalysts() -> None:
    await init_db()
    now = datetime.utcnow()
    samples = [
        {
            "headline": "NVDA datacenter demand headline crosses wires",
            "summary": "Multiple sources reporting hyperscaler capex acceleration.",
            "primary_ticker": "NVDA",
            "related_tickers": ["AMD", "SMCI"],
            "direction": "bullish",
            "catalyst_type": "product",
            "impact_score": 8,
            "confidence_score": 7,
            "thesis": "Demand narrative resurfacing; watch for price confirmation above prior day high.",
            "current_market_reaction": "Price +2.1% · Rel vol 1.8x",
            "strategy_classification": "volatility_expansion",
            "half_life": "1-3_days",
            "source_name": "demo",
            "source_url": "https://example.com",
        },
        {
            "headline": "FDA panel timing rumor hits biotech tape",
            "summary": "Unconfirmed social chatter on PDUFA adjacent names.",
            "primary_ticker": "MRNA",
            "related_tickers": ["BNTX"],
            "direction": "volatility",
            "catalyst_type": "regulatory",
            "impact_score": 6,
            "confidence_score": 4,
            "thesis": "High impact but low confirmation — event watchlist only until primary source confirms.",
            "current_market_reaction": "Price +0.8% · Rel vol 1.2x",
            "strategy_classification": "event_watchlist",
            "half_life": "intraday",
            "source_name": "demo",
            "source_url": "https://example.com",
        },
    ]

    for s in samples:
        cluster_id = await upsert_cluster(
            cluster_key=f"demo-{s['primary_ticker']}",
            canonical_title=s["headline"],
            primary_ticker=s["primary_ticker"],
        )
        await insert_scored_catalyst(
            {
                **s,
                "cluster_id": cluster_id,
                "published_at": (now - timedelta(minutes=30)).isoformat(),
                "detected_at": now.isoformat(),
                "confirmation_signals": ["Price moving with headline"],
                "invalidation_signals": ["Reversal below VWAP"],
                "key_risks": ["Headline may be recycled", "IV already elevated"],
                "market_reaction_snapshot": {"pct_change": 2.1, "relative_volume": 1.8},
                "scored": True,
            }
        )
    print(f"Seeded {len(samples)} demo catalysts")


if __name__ == "__main__":
    asyncio.run(seed_catalysts())
