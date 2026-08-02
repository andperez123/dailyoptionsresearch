from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from config import settings
from models import BriefingContent, SourceLink, SportsAngle, SportsBetDecision
from pipeline.llm import chat_tuning, responses_tuning
from pipeline.news import NewsItem
from pipeline.odds import SportsEvent
from pipeline.options import OptionsSnapshot
from pipeline.reddit import RedditPost
from pipeline.research import build_ticker_dossiers, validate_narratives
from pipeline.sports_strategies import BetDecision, decision_to_dict

logger = logging.getLogger(__name__)


def compute_buzz_zscores(
    today_counts: dict[str, int],
    history: dict[str, list[int]],
    window_days: int | None = None,
) -> dict[str, float]:
    """Buzz as a z-score against each ticker's trailing daily baseline.

    Replaces yesterday-only percent change, which mixed units (new tickers got
    absolute counts) and amplified 1→2 mention noise. Missing history days are
    zero-padded so a genuinely new spike still scores high, while the std-dev
    floor of 1 keeps sparse counts from dividing by ~0."""
    window = window_days or settings.buzz_baseline_days
    zscores: dict[str, float] = {}
    for ticker, count in today_counts.items():
        past = list(history.get(ticker, []))[-window:]
        past += [0] * (window - len(past))
        mean = sum(past) / window
        variance = sum((x - mean) ** 2 for x in past) / window
        std = max(variance**0.5, 1.0)
        zscores[ticker] = round((count - mean) / std, 2)
    return zscores


def select_top_tickers(
    counts: dict[str, int | float],
    limit: int | None = None,
    universe: set[str] | None = None,
) -> list[str]:
    """Top tickers by buzz score, restricted to real listed symbols when a
    universe is available (None means validation was impossible — do not
    filter, or an outage would blank the watchlist)."""
    limit = limit or settings.max_tickers
    candidates = (
        {t: v for t, v in counts.items() if t in universe} if universe is not None else counts
    )
    return sorted(candidates, key=candidates.get, reverse=True)[:limit]


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
            "summary": (getattr(n, "summary", "") or "")[:400],
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
                "pct_change": getattr(snap, "pct_change", None),
                "nearest_expiry": snap.nearest_expiry,
                "next_expiry": getattr(snap, "next_expiry", None),
                "avg_iv": snap.avg_iv,
                "atm_iv": getattr(snap, "atm_iv", None),
                "call_put_iv_skew": getattr(snap, "call_put_iv_skew", None),
                "iv_regime": getattr(snap, "iv_regime", None),
                "iv_rank": getattr(snap, "iv_rank", None),
                "realized_vol_20d": getattr(snap, "realized_vol_20d", None),
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
    ticker_dossiers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "research_contract": {
            "max_source_age_hours": settings.briefing_news_max_age_hours,
            "min_independent_sources": settings.min_independent_sources,
            "require_multi_source_narratives": settings.require_multi_source_narratives,
            "rules": [
                "Only write full narratives for tickers with multi-source dossiers (meets_multi_source_bar=true).",
                "Insight must synthesize across sources — never rewrite a single headline.",
                "Prefer strategy_candidates from dossiers over naked long calls/puts.",
                "Use only recent packet data for 'why now'; flag stale claims.",
            ],
        },
        "ticker_dossiers": ticker_dossiers or [],
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
    bet_decisions: list[BetDecision] | None = None,
) -> dict[str, Any]:
    return {
        "bet_decision_contract": {
            "horizon_days": settings.sports_bet_horizon_days,
            "rules": [
                "engine_bet_decisions are deterministic picks from cross-book pricing "
                "(vig-removed consensus vs best available price).",
                "Sports angles MUST be built around engine_bet_decisions when present — "
                "lead with the pick, then the story behind it.",
                "Never invent odds, edges, or picks not present in engine_bet_decisions "
                "or ranked_odds_events.",
            ],
        },
        "engine_bet_decisions": [decision_to_dict(d) for d in (bet_decisions or [])[:10]],
        "sports_reddit": _serialize_posts(sports_posts),
        "ranked_odds_events": _serialize_odds(odds),
        "matched_news": sports_news or [],
    }


SYSTEM_PROMPT = """You are a multi-source market and sports research editor.
Write source-grounded daily briefings for a research terminal — not trade picks.

Hard rules:
- Output ONLY valid JSON matching the schema exactly.
- Stock narratives MUST be grounded in ticker_dossiers with meets_multi_source_bar=true.
- Every narrative needs ≥2 independent sources (different domains/providers). Cite real URLs.
- The "insight" field must be a non-obvious synthesis across sources + market/options data —
  NEVER a paraphrase of a single headline.
- Separate observations (what sources say) from inference (your synthesis).
- Prefer dossier strategy_candidates. Do NOT default to naked long calls/puts.
  Use multi-leg structures: debit/credit spreads, calendars, diagonals, iron condors,
  strangles, jade lizards, risk reversals — chosen for the IV regime and catalyst.
- Explain edge: why that structure makes money vs a simple call/put.
- Do NOT invent matchups, odds, injuries, or public-vs-sharp claims.
- Sports angles must reference a matchup present in RANKED ODDS EVENTS.
- When engine_bet_decisions exist, build sports angles around those picks first:
  state the decision (selection, market, price, stake) in line_note, then narrate
  the supporting story and what would confirm or invalidate the number.
  Take a stance — the reader wants a decision, not a survey.
- why_now must use today's fresh packet data (age within research_contract max hours).
- Degen score 1 = conservative, 5 = speculative. Include risk framing.
- This is entertainment/research, not financial advice.
"""


def build_user_prompt(
    stock_packet: dict[str, Any],
    sports_packet: dict[str, Any],
) -> str:
    return f"""Create today's narrative research briefing from these deterministic packets.
Use web search only to corroborate or enrich tickers/events already in the packets —
never to invent a brand-new thesis with no packet support.
Prioritize ticker_dossiers where meets_multi_source_bar=true and corroborated_claims exist.
Prioritize live/upcoming sports with the highest relevance_score.

STOCK RESEARCH PACKET:
{json.dumps(stock_packet, indent=2)}

SPORTS RESEARCH PACKET:
{json.dumps(sports_packet, indent=2)}

Return JSON with this exact structure:
{{
  "summary": "2-3 sentence overview of today's dominant multi-source stories",
  "narratives": [
    {{
      "title": "string",
      "tickers": ["TICK"],
      "story": "what independent sources agree/disagree on",
      "why_now": "why it matters today using fresh packet evidence",
      "insight": "non-obvious cross-source synthesis (not a headline rewrite)",
      "priced_in": "what options/price action already reflects",
      "bull_case": "string",
      "bear_case": "string",
      "catalysts": ["date or event"],
      "confirmation_points": ["what would strengthen the thesis"],
      "invalidation_points": ["what would break the thesis"],
      "degen_score": 1-5,
      "options_plays": [
        {{
          "ticker": "TICK",
          "direction": "bullish|bearish|neutral|volatility",
          "strategy_type": "debit_call_spread|credit_put_spread|iron_condor|long_strangle|calendar_call|diagonal_call|jade_lizard|risk_reversal|...",
          "structure": "human-readable legs summary",
          "strike_zone": "e.g. $150/$155 call debit spread",
          "expiry": "YYYY-MM-DD or near→far",
          "legs": [{{"action":"buy|sell","option_type":"call|put","strike":"150","expiry":"YYYY-MM-DD","quantity":1}}],
          "thesis": "why this trade",
          "edge": "why this structure makes money vs naked call/put",
          "iv_note": "IV regime note",
          "max_loss": "string",
          "max_gain": "string",
          "breakeven": "string",
          "when_it_wins": "string",
          "when_it_loses": "string",
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
      "note": "on radar — missing multi-source corroboration or still forming"
    }}
  ]
}}

Produce 2-5 multi-source narratives (quality over quantity), 2-4 sports angles, and 3-8 radar items.
Single-source buzz belongs on radar, not as a full narrative."""


def _normalize_matchup(value: str) -> str:
    return re.sub(r"[^a-z0-9@ ]", "", value.lower()).strip()


def _teams_from_matchup(matchup: str) -> set[str]:
    parts = re.split(r"\s+@\s+|\s+vs\.?\s+|\s+v\s+", matchup, flags=re.IGNORECASE)
    return {_normalize_matchup(part) for part in parts if part.strip()}


def validate_sports_angles(
    angles: list[dict[str, Any]],
    odds: list[SportsEvent],
    sports_posts: list[RedditPost],
    bet_decisions: list[BetDecision] | None = None,
) -> list[SportsAngle]:
    odds_index: dict[str, SportsEvent] = {}
    for event in odds:
        odds_index[_normalize_matchup(f"{event.away_team} @ {event.home_team}")] = event
        if event.event_id:
            odds_index[event.event_id] = event

    decision_index: dict[str, BetDecision] = {}
    for decision in bet_decisions or []:
        if decision.event_key:
            decision_index[decision.event_key] = decision
        decision_index[_normalize_matchup(decision.matchup)] = decision

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

        matched_decision = decision_index.get(event.event_id) or decision_index.get(
            _normalize_matchup(f"{event.away_team} @ {event.home_team}")
        )
        bet_decision = (
            SportsBetDecision.model_validate(decision_to_dict(matched_decision))
            if matched_decision
            else None
        )

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
                bet_decision=bet_decision,
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
                    text={"format": {"type": "json_object"}},
                    **responses_tuning(
                        settings.openai_model,
                        temperature=0.45,
                        reasoning_effort=settings.openai_reasoning_effort,
                    ),
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
        **chat_tuning(settings.openai_model, temperature=0.45, max_tokens=6000),
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
    sports_bet_decisions: list[BetDecision] | None = None,
    top_tickers: list[str] | None = None,
) -> BriefingContent:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    # Prefer the caller's universe-validated watchlist; fall back to raw counts
    if top_tickers is None:
        top_tickers = select_top_tickers(ticker_counts)
    dossiers = build_ticker_dossiers(
        tickers=top_tickers,
        news=news,
        finance_posts=finance_posts,
        options=options,
        overnight_catalysts=overnight_catalysts or [],
        ticker_counts=ticker_counts,
        buzz_deltas=buzz_deltas,
        macro_context=macro_context,
        max_age_hours=settings.briefing_news_max_age_hours,
    )

    stock_packet = build_stock_research_packet(
        finance_posts,
        news,
        options,
        ticker_counts,
        buzz_deltas,
        overnight_catalysts,
        macro_context,
        ticker_dossiers=dossiers,
    )
    sports_packet = build_sports_research_packet(
        sports_posts, odds, sports_news, bet_decisions=sports_bet_decisions
    )
    user_prompt = build_user_prompt(stock_packet, sports_packet)

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    raw, citations, api_mode = await _generate_briefing_json(client, user_prompt)
    data = _parse_model_json(raw)

    sports_angles = validate_sports_angles(
        data.get("sports_angles", []), odds, sports_posts, bet_decisions=sports_bet_decisions
    )
    data["sports_angles"] = [angle.model_dump(mode="json") for angle in sports_angles]

    for narrative in data.get("narratives", []):
        sources = narrative.get("sources", [])
        if citations and len(sources) < 2:
            for citation in citations[:3]:
                if citation["url"] and citation not in sources:
                    sources.append(citation)
            narrative["sources"] = sources

    before_count = len(data.get("narratives") or [])
    raw_narratives = data.get("narratives") or []
    data["narratives"] = validate_narratives(
        raw_narratives,
        dossiers,
        require_multi_source=settings.require_multi_source_narratives,
        options=options,
    )
    if not data["narratives"] and raw_narratives and settings.require_multi_source_narratives:
        # Thin corroboration day — keep narratives but mark low confidence
        data["narratives"] = validate_narratives(
            raw_narratives, dossiers, require_multi_source=False, options=options
        )
        for narrative in data["narratives"]:
            rq = narrative.setdefault("research_quality", {})
            rq["warning"] = "Multi-source bar not met — thesis marked low confidence"
            rq["meets_multi_source_bar"] = False
    dropped = before_count - len(data["narratives"])

    # Auto-radar for strong-buzz tickers that failed the multi-source bar
    radar = list(data.get("radar") or [])
    radar_tickers = {str(r.get("ticker", "")).upper() for r in radar}
    for dossier in dossiers:
        t = dossier["ticker"]
        quality = dossier.get("research_quality") or {}
        if quality.get("meets_multi_source_bar"):
            continue
        if t in radar_tickers:
            continue
        if dossier.get("mention_count", 0) < 2:
            continue
        radar.append(
            {
                "ticker": t,
                "buzz_delta": dossier.get("buzz_delta", 0.0),
                "mention_count": dossier.get("mention_count", 0),
                "note": (
                    f"Buzz without multi-source confirmation "
                    f"({quality.get('independent_source_count', 0)} independent sources, "
                    f"{quality.get('news_domain_count', 0)} news domains)"
                ),
            }
        )
        radar_tickers.add(t)
    data["radar"] = radar[:10]

    multi_source_ready = sum(
        1 for d in dossiers if d.get("research_quality", {}).get("meets_multi_source_bar")
    )
    data["raw_stats"] = {
        "ticker_counts": dict(list(ticker_counts.items())[:20]),
        "buzz_deltas": dict(list(buzz_deltas.items())[:20]),
        "reddit_posts_collected": len(finance_posts) + len(sports_posts),
        "news_items_collected": len(news),
        "options_snapshots": len(options),
        "sports_events": len(odds),
        "sports_bet_decisions": len(sports_bet_decisions or []),
        "overnight_catalysts": len(overnight_catalysts or []),
        "web_citations": len(citations),
        "ticker_dossiers": len(dossiers),
        "multi_source_dossiers": multi_source_ready,
        "narratives_dropped_single_source": dropped,
    }
    data["research_metadata"] = {
        "model": settings.openai_model,
        "api_mode": api_mode,
        "web_search_enabled": api_mode == "responses_web",
        "stock_packet_size": len(json.dumps(stock_packet)),
        "sports_packet_size": len(json.dumps(sports_packet)),
        "validated_sports_angles": len(sports_angles),
        "briefing_news_max_age_hours": settings.briefing_news_max_age_hours,
        "min_independent_sources": settings.min_independent_sources,
        "require_multi_source_narratives": settings.require_multi_source_narratives,
        "strategy_engine": "strategies-v2",
    }
    return BriefingContent.model_validate(data)
