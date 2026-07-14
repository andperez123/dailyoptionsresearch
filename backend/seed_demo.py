#!/usr/bin/env python3
"""Seed a demo briefing for UI testing without OpenAI API calls."""

import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import init_db, save_briefing
from models import BriefingContent, Narrative, OptionsPlay, RadarItem, SourceLink, SportsAngle


async def seed() -> None:
    await init_db()
    content = BriefingContent(
        summary=(
            "Meme momentum is back on WSB with NVDA and TSLA dominating chatter. "
            "Options flow shows heavy weekly call buying on mega-cap tech while "
            "sportsbook Reddit is hammering NBA unders after a high-scoring week."
        ),
        narratives=[
            Narrative(
                title="AI Capex Reflex Rally",
                tickers=["NVDA", "AMD", "SMCI"],
                story="Reddit is reviving the AI trade after fresh datacenter demand headlines.",
                why_now="Earnings season + WSB YOLO threads resurfacing on weekly calls.",
                bull_case="Continued hyperscaler spend and gamma squeeze on NVDA weeklies.",
                bear_case="Crowded long, IV expensive, any guidance miss gets punished hard.",
                catalysts=["NVDA earnings", "CPI print"],
                degen_score=4,
                options_plays=[
                    OptionsPlay(
                        ticker="NVDA",
                        direction="call",
                        strike_zone="$140-145 calls",
                        expiry="next weekly",
                        iv_note="IV elevated — consider spreads over naked calls",
                        degen_score=4,
                        risk_note="One red day wipes premium on weeklies",
                    )
                ],
                sources=[
                    SourceLink(
                        title="NVDA weekly YOLO thread",
                        url="https://www.reddit.com/r/wallstreetbets/",
                        source_type="reddit",
                    )
                ],
            ),
            Narrative(
                title="TSLA Sentiment Snapback",
                tickers=["TSLA"],
                story="Tesla chatter flipped bullish after delivery rumor cycle on r/stocks.",
                why_now="Buzz delta spiked vs yesterday with call volume outpacing puts.",
                bull_case="Short squeeze fuel if price holds key moving average.",
                bear_case="Elon headline risk and IV crush after events.",
                catalysts=["Delivery numbers"],
                degen_score=3,
                options_plays=[
                    OptionsPlay(
                        ticker="TSLA",
                        direction="call spread",
                        strike_zone="$250/$260 call spread",
                        expiry="2 weeks",
                        iv_note="Moderate IV",
                        degen_score=3,
                        risk_note="Defined risk but still theta decay",
                    )
                ],
                sources=[],
            ),
        ],
        sports_angles=[
            SportsAngle(
                title="Public Hammering the Over",
                sport="NBA",
                matchup="Lakers vs Celtics",
                narrative="After three straight overs, r/sportsbook is loudly fading the total.",
                line_note="Total opened 228.5, now 232.5",
                public_vs_sharp="Public on over; contrarian under angle getting traction",
                degen_score=3,
                sources=[
                    SourceLink(
                        title="Fade the NBA over thread",
                        url="https://www.reddit.com/r/sportsbook/",
                        source_type="reddit",
                    )
                ],
            )
        ],
        radar=[
            RadarItem(ticker="GME", buzz_delta=2.5, mention_count=18, note="Meme chatter returning but no catalyst yet"),
            RadarItem(ticker="PLTR", buzz_delta=1.2, mention_count=12, note="Gov contract rumors, watch for confirmation"),
        ],
        generated_at=datetime.utcnow(),
        raw_stats={"demo": True},
    )
    await save_briefing(date.today(), content)
    print("Demo briefing seeded for", date.today().isoformat())


if __name__ == "__main__":
    asyncio.run(seed())
