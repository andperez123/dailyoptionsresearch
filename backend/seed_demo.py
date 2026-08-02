#!/usr/bin/env python3
"""Seed a demo briefing for UI testing without OpenAI API calls."""

import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import init_db, save_briefing
from models import (
    BriefingContent,
    Narrative,
    OptionsPlay,
    RadarItem,
    SourceLink,
    SportsAngle,
    SportsBetDecision,
)


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
                insight="Call-heavy Reddit flow lines up with elevated IV — spreads beat naked weeklies.",
                priced_in="Near-term upside already partially in ATM call premiums",
                confirmation_points=["Hyperscaler capex reaffirmed", "IV stays bid into print"],
                invalidation_points=["Guidance cut", "IV crush without move"],
                options_plays=[
                    OptionsPlay(
                        ticker="NVDA",
                        direction="bullish",
                        strategy_type="debit_call_spread",
                        structure="Buy 140C / Sell 145C",
                        strike_zone="$140/$145 call debit spread",
                        expiry="next weekly",
                        edge="Defined-risk upside — cheaper than naked calls when IV is elevated",
                        thesis="Bullish AI tape with rich IV — prefer spread over YOLO calls",
                        iv_note="IV elevated — debit spread preferred",
                        max_loss="Net debit paid",
                        max_gain="Width minus debit",
                        when_it_wins="Push through 140 toward 145",
                        when_it_loses="Stall below 140 into expiry",
                        degen_score=3,
                        risk_note="Still needs directional follow-through before theta wins",
                    )
                ],
                sources=[
                    SourceLink(
                        title="NVDA weekly YOLO thread",
                        url="https://www.reddit.com/r/wallstreetbets/",
                        source_type="reddit",
                    ),
                    SourceLink(
                        title="Datacenter demand headlines",
                        url="https://finance.yahoo.com/",
                        source_type="news",
                    ),
                ],
                research_quality={
                    "independent_source_count": 2,
                    "meets_multi_source_bar": True,
                    "news_domain_count": 1,
                },
            ),
            Narrative(
                title="TSLA Sentiment Snapback",
                tickers=["TSLA"],
                story="Tesla chatter flipped bullish after delivery rumor cycle across social + news.",
                why_now="Buzz delta spiked vs yesterday with call volume outpacing puts.",
                insight="Social acceleration without multi-outlet confirmation — treat as radar-grade until filings/news catch up.",
                priced_in="Short-dated calls already pricing a bounce",
                bull_case="Short squeeze fuel if price holds key moving average.",
                bear_case="Elon headline risk and IV crush after events.",
                catalysts=["Delivery numbers"],
                degen_score=3,
                options_plays=[
                    OptionsPlay(
                        ticker="TSLA",
                        direction="bullish",
                        strategy_type="credit_put_spread",
                        structure="Sell 250P / Buy 240P",
                        strike_zone="$250/$240 put credit spread",
                        expiry="2 weeks",
                        edge="Collect premium with bullish/neutral bias under support",
                        thesis="Bullish snapback with defined downside",
                        iv_note="Moderate-to-elevated IV helps credit",
                        max_loss="Width minus credit",
                        max_gain="Net credit",
                        degen_score=3,
                        risk_note="Gap risk through short put on headline shock",
                    )
                ],
                sources=[
                    SourceLink(
                        title="Delivery rumor cycle",
                        url="https://www.reddit.com/r/stocks/",
                        source_type="reddit",
                    )
                ],
                research_quality={
                    "independent_source_count": 1,
                    "meets_multi_source_bar": False,
                    "warning": "Multi-source bar not met — thesis marked low confidence",
                },
            ),
        ],
        sports_angles=[
            SportsAngle(
                title="Public Hammering the Over",
                sport="NBA",
                matchup="Lakers vs Celtics",
                narrative="After three straight overs, r/sportsbook is loudly fading the total.",
                why_now="Three consecutive overs have the market stretched on the total.",
                line_note="Total opened 228.5, now 232.5",
                priced_in="Market already leaning over after recent high-scoring games",
                confirmation_points=["Injury report clears starters"],
                invalidation_points=["Pace spikes in first quarter"],
                source_event_key="demo-nba",
                degen_score=3,
                sources=[
                    SourceLink(
                        title="Fade the NBA over thread",
                        url="https://www.reddit.com/r/sportsbook/",
                        source_type="reddit",
                    )
                ],
                bet_decision=SportsBetDecision(
                    event_key="demo-nba",
                    sport_key="basketball_nba",
                    sport_title="NBA",
                    home_team="Celtics",
                    away_team="Lakers",
                    matchup="Lakers @ Celtics",
                    commence_time=datetime.utcnow().isoformat() + "Z",
                    market="totals",
                    market_label="total",
                    selection="Under",
                    point=232.5,
                    best_price=-105,
                    best_bookmaker="DraftKings",
                    consensus_probability=0.545,
                    implied_probability=0.512,
                    edge_pct=3.3,
                    ev_pct=6.4,
                    kelly_fraction=0.069,
                    stake_units=1.7,
                    decision="bet",
                    confidence=6.2,
                    rationale=(
                        "BET Under 232.5 total -105 @ DraftKings: the best available price is "
                        "meaningfully better than the cross-book fair value (+6.4% EV). "
                        "Stake 1.7u (quarter-Kelly, capped)."
                    ),
                    key_factors=[
                        "Fair probability 54.5% (consensus of the other 3 book(s)) vs 51.2% "
                        "implied at the best price (+3.3 pts edge)",
                        "Expected value +6.4% per unit staked",
                        "Edge persisted across scans — not a transient quote",
                    ],
                    risks=[
                        "Fair value is derived from other bookmakers' prices, not a true "
                        "outcome model — correlated book errors inflate apparent edge",
                        "Late injury/lineup news can invalidate the number instantly",
                    ],
                    research_checklist=[
                        "Check rest spots: back-to-backs and 3-games-in-4-nights fade legs",
                        "Confirm star-player load management status",
                        "Re-check the line at 2-3 books right before bet placement — edge decays fast",
                    ],
                    line_movement_note="Under: 228.5 (-110) -> 232.5 (-105)",
                    news_support_count=1,
                ),
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
