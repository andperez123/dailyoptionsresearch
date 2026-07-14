from __future__ import annotations

import json
from datetime import date, timedelta

from openai import AsyncOpenAI

from config import settings
from models import BriefingContent
from pipeline.news import NewsItem
from pipeline.odds import SportsEvent
from pipeline.options import OptionsSnapshot
from pipeline.reddit import RedditPost, count_ticker_mentions


def compute_buzz_delta(
    today_counts: dict[str, int],
    yesterday_counts: dict[str, int],
) -> dict[str, float]:
    deltas: dict[str, float] = {}
    for ticker, count in today_counts.items():
        prev = yesterday_counts.get(ticker, 0)
        if prev == 0:
            deltas[ticker] = float(count)
        else:
            deltas[ticker] = round((count - prev) / prev, 2)
    return deltas


def select_top_tickers(
    counts: dict[str, int],
    limit: int | None = None,
) -> list[str]:
    limit = limit or settings.max_tickers
    return sorted(counts, key=counts.get, reverse=True)[:limit]


def _serialize_posts(posts: list[RedditPost], limit: int = 20) -> list[dict]:
    return [
        {
            "subreddit": p.subreddit,
            "title": p.title,
            "text": (p.selftext or "")[:600],
            "url": p.url,
            "score": p.score,
            "comments": p.top_comments[:3],
        }
        for p in posts[:limit]
    ]


def _serialize_news(news: list[NewsItem], limit: int = 25) -> list[dict]:
    return [
        {
            "title": n.title,
            "url": n.url,
            "source": n.source,
            "ticker": n.ticker,
        }
        for n in news[:limit]
    ]


def _serialize_options(options: list[OptionsSnapshot]) -> list[dict]:
    serialized = []
    for snap in options:
        serialized.append(
            {
                "ticker": snap.ticker,
                "price": snap.current_price,
                "nearest_expiry": snap.nearest_expiry,
                "avg_iv": snap.avg_iv,
                "put_call_volume_ratio": snap.put_call_volume_ratio,
                "notable_calls": [
                    {
                        "strike": c.strike,
                        "volume": c.volume,
                        "oi": c.open_interest,
                        "iv": c.implied_volatility,
                    }
                    for c in snap.notable_calls
                ],
                "notable_puts": [
                    {
                        "strike": c.strike,
                        "volume": c.volume,
                        "oi": c.open_interest,
                        "iv": c.implied_volatility,
                    }
                    for c in snap.notable_puts
                ],
                "error": snap.error,
            }
        )
    return serialized


def _serialize_odds(events: list[SportsEvent], limit: int = 12) -> list[dict]:
    return [
        {
            "sport": e.sport,
            "matchup": f"{e.away_team} @ {e.home_team}",
            "commence_time": e.commence_time,
            "markets": [
                {
                    "key": m.key,
                    "outcomes": [{"name": o.name, "price": o.price} for o in m.outcomes],
                }
                for m in e.markets
            ],
        }
        for e in events[:limit]
    ]


SYSTEM_PROMPT = """You are a sharp but entertaining market research analyst writing for degen traders.
Synthesize Reddit chatter, news, options flow, and sports betting angles into actionable narratives.

Rules:
- Output ONLY valid JSON matching the schema exactly.
- Be specific with tickers, strike zones, and expiries when suggesting options plays.
- Degen score 1 = conservative, 5 = full casino mode.
- Always include risk framing. This is entertainment, not financial advice.
- Connect sports betting narratives to market sentiment when relevant.
- Prefer narratives with real catalysts and unusual options activity.
- Include source URLs from the input data when available.
"""


def build_user_prompt(
    finance_posts: list[RedditPost],
    sports_posts: list[RedditPost],
    news: list[NewsItem],
    options: list[OptionsSnapshot],
    odds: list[SportsEvent],
    ticker_counts: dict[str, int],
    buzz_deltas: dict[str, float],
    overnight_catalysts: list[dict] | None = None,
) -> str:
    return f"""Create today's degen research briefing from this data.

DISTINCTION: Narratives = themes that matter. Catalysts = what just happened. Setups = what deserves investigation.
Use OVERNIGHT CATALYSTS as primary input for narratives — these are ranked signal clusters, not raw headlines.

OVERNIGHT CATALYSTS (ranked signals):
{json.dumps(overnight_catalysts or [], indent=2)}

TICKER MENTIONS (count): {json.dumps(dict(list(ticker_counts.items())[:20]))}
BUZZ DELTA vs yesterday: {json.dumps(dict(list(buzz_deltas.items())[:20]))}

FINANCE REDDIT POSTS:
{json.dumps(_serialize_posts(finance_posts), indent=2)}

SPORTS BETTING REDDIT POSTS:
{json.dumps(_serialize_posts(sports_posts), indent=2)}

NEWS HEADLINES:
{json.dumps(_serialize_news(news), indent=2)}

OPTIONS SNAPSHOTS:
{json.dumps(_serialize_options(options), indent=2)}

SPORTS ODDS:
{json.dumps(_serialize_odds(odds), indent=2)}

Return JSON with this exact structure:
{{
  "summary": "2-3 sentence overview of today's vibe",
  "narratives": [
    {{
      "title": "string",
      "tickers": ["TICK"],
      "story": "what's the narrative",
      "why_now": "why it matters today",
      "bull_case": "string",
      "bear_case": "string",
      "catalysts": ["date or event"],
      "degen_score": 1-5,
      "options_plays": [
        {{
          "ticker": "TICK",
          "direction": "call/put/spread",
          "strike_zone": "e.g. $150-155 calls",
          "expiry": "YYYY-MM-DD or weekly",
          "iv_note": "cheap/expensive IV note",
          "degen_score": 1-5,
          "risk_note": "what can go wrong"
        }}
      ],
      "sources": [{{"title": "string", "url": "string", "source_type": "reddit|news"}}]
    }}
  ],
  "sports_angles": [
    {{
      "title": "string",
      "sport": "NFL/NBA/etc",
      "matchup": "Team A vs Team B",
      "narrative": "the betting angle",
      "line_note": "notable line or odds move",
      "public_vs_sharp": "where public money seems vs contrarian read",
      "degen_score": 1-5,
      "sources": [{{"title": "string", "url": "string", "source_type": "reddit|odds"}}]
    }}
  ],
  "radar": [
    {{
      "ticker": "TICK",
      "buzz_delta": 0.0,
      "mention_count": 0,
      "note": "why it's on radar but not a full narrative yet"
    }}
  ]
}}

Produce 3-6 narratives, 2-4 sports angles, and 3-8 radar items."""


async def synthesize_briefing(
    finance_posts: list[RedditPost],
    sports_posts: list[RedditPost],
    news: list[NewsItem],
    options: list[OptionsSnapshot],
    odds: list[SportsEvent],
    ticker_counts: dict[str, int],
    buzz_deltas: dict[str, float],
    overnight_catalysts: list[dict] | None = None,
) -> BriefingContent:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    user_prompt = build_user_prompt(
        finance_posts,
        sports_posts,
        news,
        options,
        odds,
        ticker_counts,
        buzz_deltas,
        overnight_catalysts,
    )

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        max_tokens=6000,
    )

    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)
    data["raw_stats"] = {
        "ticker_counts": dict(list(ticker_counts.items())[:20]),
        "buzz_deltas": dict(list(buzz_deltas.items())[:20]),
        "reddit_posts_collected": len(finance_posts) + len(sports_posts),
        "news_items_collected": len(news),
        "options_snapshots": len(options),
        "sports_events": len(odds),
        "overnight_catalysts": len(overnight_catalysts or []),
    }
    return BriefingContent.model_validate(data)
