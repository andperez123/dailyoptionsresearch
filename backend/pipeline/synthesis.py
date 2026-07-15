from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from config import settings
from models import BriefingContent, SourceLink, SportsAngle
from pipeline.news import NewsItem
from pipeline.odds import SportsEvent
from pipeline.options import OptionsSnapshot
from pipeline.reddit import RedditPost

logger = logging.getLogger(__name__)


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


def _serialize_news(news: list[NewsItem], limit: int = 30) -> list[dict]:
    return [
        {
            "title": n.title,
            "url": n.url,
            "source": n.source,
            "ticker": n.ticker,
            "published": n.published,
            "source_tier": getattr(n, "source_tier", "rss"),
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
            "event_id": e.event_id,
            "sport": e.sport,
            "sport_title": e.sport_title,
            "matchup": f"{e.away_team} @ {e.home_team}",
            "commence_time": e.commence_time,
            "relevance_score": e.relevance_score,
            "relevance_factors": e.relevance_factors,
            "bookmaker_count": e.bookmaker_count,
            "markets": [
                {
                    "key": m.key,
                    "outcomes": [
                        {"name": o.name, "price": o.price, "point": o.point}
                        for o in m.outcomes
                    ],
                }
                for m in e.markets
            ],
        }
        for e in events[:limit]
    ]


def build_stock_research_packet(
    finance_posts: list[RedditPost],
    news: list[NewsItem],
    options: list[OptionsSnapshot],
    ticker_counts: dict[str, int],
    buzz_deltas: dict[str, float],
    overnight_catalysts: list[dict] | None,
    macro_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "overnight_catalysts": overnight_catalysts or [],
        "ticker_mentions": dict(list(ticker_counts.items())[:20]),
        "buzz_deltas": dict(list(buzz_deltas.items())[:20]),
        "finance_reddit": _serialize_posts(finance_posts),
        "news": _serialize_news(news),
        "options": _serialize_options(options),
        "macro_context": macro_context or [],
    }


def build_sports_research_packet(
    sports_posts: list[RedditPost],
    odds: list[SportsEvent],
    sports_news: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "sports_reddit": _serialize_posts(sports_posts),
        "ranked_odds_events": _serialize_odds(odds),
        "matched_news": sports_news or [],
    }


SYSTEM_PROMPT = """You are a narrative market and sports research editor.
Write source-grounded daily briefings for a research terminal — not trade picks.

Rules:
- Output ONLY valid JSON matching the schema exactly.
- Every narrative must cite real URLs from the provided packets or web search results.
- Do NOT invent matchups, odds, injuries, or public-vs-sharp claims.
- Sports angles must reference a matchup present in RANKED ODDS EVENTS.
- Stock narratives must connect to catalysts, news, or options data in the packet.
- Prefer the dominant story: why it matters now, what is priced in, what confirms or invalidates it.
- Degen score 1 = conservative, 5 = speculative. Include risk framing.
- This is entertainment/research, not financial advice.
"""


def build_user_prompt(
    stock_packet: dict[str, Any],
    sports_packet: dict[str, Any],
) -> str:
    return f"""Create today's narrative research briefing from these deterministic packets.
Use web search only to enrich current reporting for the events and tickers already in the packets.
Prioritize live and upcoming competitions with the highest relevance_score.

STOCK RESEARCH PACKET:
{json.dumps(stock_packet, indent=2)}

SPORTS RESEARCH PACKET:
{json.dumps(sports_packet, indent=2)}

Return JSON with this exact structure:
{{
  "summary": "2-3 sentence overview of today's dominant stories",
  "narratives": [
    {{
      "title": "string",
      "tickers": ["TICK"],
      "story": "dominant narrative",
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
      "sources": [{{"title": "string", "url": "string", "source_type": "news|reddit|catalyst|web"}}]
    }}
  ],
  "sports_angles": [
    {{
      "title": "string",
      "sport": "competition name",
      "matchup": "Team A @ Team B",
      "source_event_key": "event id from ranked odds when available",
      "narrative": "the story behind the line",
      "why_now": "why this event matters now",
      "line_note": "specific line/odds context from packet only",
      "priced_in": "what the market already reflects",
      "confirmation_points": ["what would strengthen the read"],
      "invalidation_points": ["what would break the read"],
      "degen_score": 1-5,
      "sources": [{{"title": "string", "url": "string", "source_type": "news|reddit|odds|web"}}]
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


def _normalize_matchup(value: str) -> str:
    return re.sub(r"[^a-z0-9@ ]", "", value.lower()).strip()


def _teams_from_matchup(matchup: str) -> set[str]:
    parts = re.split(r"\s+@\s+|\s+vs\.?\s+|\s+v\s+", matchup, flags=re.IGNORECASE)
    return {_normalize_matchup(part) for part in parts if part.strip()}


def validate_sports_angles(
    angles: list[dict[str, Any]],
    odds: list[SportsEvent],
    sports_posts: list[RedditPost],
) -> list[SportsAngle]:
    odds_index: dict[str, SportsEvent] = {}
    for event in odds:
        odds_index[_normalize_matchup(f"{event.away_team} @ {event.home_team}")] = event
        if event.event_id:
            odds_index[event.event_id] = event

    post_urls = {p.url for p in sports_posts if p.url}
    validated: list[SportsAngle] = []
    for raw in angles:
        matchup = raw.get("matchup", "")
        normalized = _normalize_matchup(matchup)
        event = odds_index.get(raw.get("source_event_key", "")) or odds_index.get(normalized)
        if not event:
            teams = _teams_from_matchup(matchup)
            event = next(
                (
                    candidate
                    for key, candidate in odds_index.items()
                    if any(team in key for team in teams if team)
                ),
                None,
            )
        if not event:
            logger.info("Dropping sports angle without matching event: %s", matchup)
            continue

        sources = [
            SourceLink.model_validate(source)
            for source in raw.get("sources", [])
            if source.get("url")
        ]
        if not sources:
            logger.info("Dropping sports angle without sources: %s", matchup)
            continue

        if not any(source.url in post_urls or source.source_type in {"news", "odds", "web"} for source in sources):
            pass

        validated.append(
            SportsAngle(
                title=raw.get("title", f"{event.sport_title} angle"),
                sport=raw.get("sport", event.sport_title or event.sport),
                matchup=f"{event.away_team} @ {event.home_team}",
                source_event_key=event.event_id,
                narrative=raw.get("narrative", ""),
                why_now=raw.get("why_now", ""),
                line_note=raw.get("line_note", ""),
                priced_in=raw.get("priced_in", ""),
                confirmation_points=raw.get("confirmation_points", []),
                invalidation_points=raw.get("invalidation_points", []),
                degen_score=int(raw.get("degen_score", 3)),
                sources=sources,
            )
        )
    return validated


def _parse_model_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Model returned empty briefing content")

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        data = json.loads(fenced.group(1))
        if isinstance(data, dict):
            return data

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(text[start : end + 1])
        if isinstance(data, dict):
            return data

    raise ValueError(f"Model response was not valid JSON: {text[:240]!r}")


def _extract_response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    parts: list[str] = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for block in getattr(item, "content", None) or []:
            block_text = getattr(block, "text", None)
            if isinstance(block_text, str) and block_text.strip():
                parts.append(block_text.strip())
    return "\n".join(parts).strip()


def _extract_citations(response: Any) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    output = getattr(response, "output", None) or []
    for item in output:
        if getattr(item, "type", None) != "message":
            continue
        content = getattr(item, "content", None) or []
        for block in content:
            annotations = getattr(block, "annotations", None) or []
            for annotation in annotations:
                if getattr(annotation, "type", None) == "url_citation":
                    citations.append(
                        {
                            "title": getattr(annotation, "title", "") or "Web source",
                            "url": getattr(annotation, "url", ""),
                            "source_type": "web",
                        }
                    )
    return citations


async def _generate_briefing_json(
    client: AsyncOpenAI,
    user_prompt: str,
) -> tuple[str, list[dict[str, str]], str]:
    """Return raw JSON text, web citations, and API mode used."""
    if hasattr(client, "responses"):
        web_attempts = [True, False] if settings.openai_use_web_search else [False]
        for use_web in web_attempts:
            tools = []
            if use_web:
                tools.append(
                    {
                        "type": "web_search",
                        "search_context_size": settings.openai_web_search_context,
                    }
                )
            try:
                response = await client.responses.create(
                    model=settings.openai_model,
                    instructions=SYSTEM_PROMPT,
                    input=user_prompt,
                    tools=tools,
                    max_tool_calls=settings.openai_max_tool_calls,
                    temperature=0.45,
                    text={"format": {"type": "json_object"}},
                )
            except Exception as exc:
                logger.warning("Responses API call failed (web=%s): %s", use_web, exc)
                continue

            raw = _extract_response_text(response)
            status = getattr(response, "status", "unknown")
            if not raw:
                logger.warning("Responses API returned empty text (status=%s, web=%s)", status, use_web)
                continue
            try:
                _parse_model_json(raw)
            except ValueError as exc:
                logger.warning("Responses JSON invalid (status=%s, web=%s): %s", status, use_web, exc)
                continue
            mode = "responses_web" if use_web else "responses"
            return raw, _extract_citations(response), mode

        logger.warning("Responses API produced no parseable JSON; falling back to chat completions")

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.45,
        max_tokens=6000,
    )
    raw = response.choices[0].message.content or "{}"
    if not raw.strip():
        raise ValueError("Chat completions returned empty briefing content")
    _parse_model_json(raw)
    return raw, [], "chat_completions"


async def synthesize_briefing(
    finance_posts: list[RedditPost],
    sports_posts: list[RedditPost],
    news: list[NewsItem],
    options: list[OptionsSnapshot],
    odds: list[SportsEvent],
    ticker_counts: dict[str, int],
    buzz_deltas: dict[str, float],
    overnight_catalysts: list[dict] | None = None,
    macro_context: list[dict[str, Any]] | None = None,
    sports_news: list[dict[str, Any]] | None = None,
) -> BriefingContent:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    stock_packet = build_stock_research_packet(
        finance_posts,
        news,
        options,
        ticker_counts,
        buzz_deltas,
        overnight_catalysts,
        macro_context,
    )
    sports_packet = build_sports_research_packet(sports_posts, odds, sports_news)
    user_prompt = build_user_prompt(stock_packet, sports_packet)

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    raw, citations, api_mode = await _generate_briefing_json(client, user_prompt)
    data = _parse_model_json(raw)

    sports_angles = validate_sports_angles(data.get("sports_angles", []), odds, sports_posts)
    data["sports_angles"] = [angle.model_dump(mode="json") for angle in sports_angles]

    for narrative in data.get("narratives", []):
        sources = narrative.get("sources", [])
        if citations and len(sources) < 2:
            for citation in citations[:3]:
                if citation["url"] and citation not in sources:
                    sources.append(citation)
            narrative["sources"] = sources

    data["raw_stats"] = {
        "ticker_counts": dict(list(ticker_counts.items())[:20]),
        "buzz_deltas": dict(list(buzz_deltas.items())[:20]),
        "reddit_posts_collected": len(finance_posts) + len(sports_posts),
        "news_items_collected": len(news),
        "options_snapshots": len(options),
        "sports_events": len(odds),
        "overnight_catalysts": len(overnight_catalysts or []),
        "web_citations": len(citations),
    }
    data["research_metadata"] = {
        "model": settings.openai_model,
        "api_mode": api_mode,
        "web_search_enabled": api_mode == "responses_web",
        "stock_packet_size": len(json.dumps(stock_packet)),
        "sports_packet_size": len(json.dumps(sports_packet)),
        "validated_sports_angles": len(sports_angles),
    }
    return BriefingContent.model_validate(data)
