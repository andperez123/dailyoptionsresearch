from __future__ import annotations

import asyncio
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
from pipeline.offline import build_deterministic_briefing
from pipeline.options import OptionsSnapshot
from pipeline.reddit import RedditPost
from pipeline.report import RunReportBuilder
from pipeline.research import (
    TIER_CONFIRMED,
    TIER_DEVELOPING,
    build_ticker_dossiers,
    dossier_verdicts,
    validate_narratives,
)
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


def serialize_threads(threads: list[Any]) -> list[dict[str, Any]]:
    """Compact ongoing-narrative context for the LLM: the current thesis plus
    the last few dated updates so the model can continue the storyline."""
    serialized: list[dict[str, Any]] = []
    for thread in threads:
        serialized.append(
            {
                "ticker": thread.ticker,
                "title": thread.title,
                "status": thread.status,
                "direction": thread.direction,
                "conviction": thread.conviction,
                "current_thesis": thread.thesis,
                "started": thread.created_date.isoformat(),
                "days_tracked": thread.days_tracked,
                "recent_updates": [
                    {
                        "date": u.update_date.isoformat(),
                        "type": u.update_type,
                        "note": u.note[:300],
                    }
                    for u in thread.updates[:5]
                ],
            }
        )
    return serialized


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
                "Decisions come in three grades: 'bet' (cleared every gate), 'lean' "
                "(positive expected value that missed a gate — still a real, actionable "
                "setup to watch at the stated number), and 'pass'. Cover the bets first, "
                "then the highest-EV leans. Always take a stance on the best available "
                "setups; reserve 'nothing here' for slates where no outcome shows "
                "positive EV.",
                "Never invent odds, edges, or picks not present in engine_bet_decisions "
                "or ranked_odds_events.",
            ],
        },
        "engine_bet_decisions": [decision_to_dict(d) for d in (bet_decisions or [])[:10]],
        "sports_reddit": _serialize_posts(sports_posts, limit=12),
        "ranked_odds_events": _serialize_odds(odds),
        "matched_news": sports_news or [],
    }


# ---------------------------------------------------------------------------
# Stage 1 — per-ticker deep dives.
#
# The old pipeline made ONE call with every Reddit post, news item, options
# chain, macro series, and the whole sports slate crammed into a single
# prompt, then asked for a giant multi-section JSON. Depth was the casualty.
# Deep dives give the model one dossier at a time and demand real synthesis.
# ---------------------------------------------------------------------------

DEEP_DIVE_SYSTEM_PROMPT = """You are a senior equity + options research analyst.
You produce ONE deep, source-grounded research narrative for ONE ticker.

Hard rules:
- Output ONLY valid JSON matching the requested schema exactly.
- Ground every claim in the dossier (or web corroboration of dossier claims).
  Cite real URLs from the dossier sources.
- "insight" must be a non-obvious synthesis ACROSS sources + options/market
  data — never a paraphrase of one headline. Connect dots: what do the
  sources collectively imply that no single one states?
- "priced_in" must reference the actual options data provided (IV rank,
  regime, skew, put/call flow) — say specifically what the market already
  reflects and what it does not.
- Separate observation (what sources say) from inference (your synthesis) in
  the story: attribute claims to their outlets.
- Prefer the deterministic strategy_candidates for options plays; you may
  adapt them or propose alternatives ONLY using strikes/expiries listed in
  the dossier. NEVER naked long calls/puts as the primary idea.
- Explain the structure's edge: why it beats a simple call/put here.
- If an ongoing_thread is provided, continue that storyline: set
  thread_update.status (continuing|strengthening|weakening|resolved) and
  what_changed since the last update. If evidence contradicts the thread's
  thesis, say so — never silently ignore it. New theses use status "new".
- why_now must use fresh dossier evidence, not generic framing.
- Always deliver analysis even when sourcing is thin — lower the degen score
  and say so plainly rather than returning an empty thesis.
- Degen score 1 = conservative, 5 = speculative. Include risk framing.
- This is entertainment/research, not financial advice."""


def build_deep_dive_prompt(
    dossier: dict[str, Any],
    thread: dict[str, Any] | None,
    macro_context: list[dict[str, Any]] | None,
) -> str:
    payload = {
        "dossier": dossier,
        "ongoing_thread": thread,
        "macro_context": (macro_context or [])[:6],
    }
    return f"""Write today's deep-dive research narrative for {dossier['ticker']}.

RESEARCH DOSSIER (deterministic, pre-verified):
{json.dumps(payload, indent=2, default=str)}

Return JSON with this exact structure:
{{
  "title": "specific, informative headline (not clickbait)",
  "tickers": ["{dossier['ticker']}"],
  "story": "what independent sources report, with attribution, and where they agree/disagree",
  "why_now": "why this matters today, citing fresh dossier evidence",
  "insight": "non-obvious cross-source synthesis — the 'so what' a skimmer would miss",
  "priced_in": "what options/price action already reflects (use the dossier's IV/flow data)",
  "bull_case": "string",
  "bear_case": "string",
  "catalysts": ["date or event"],
  "confirmation_points": ["what would strengthen the thesis"],
  "invalidation_points": ["what would break the thesis"],
  "thread_update": {{"status": "new|continuing|strengthening|weakening|resolved", "what_changed": "one sentence (empty for new)"}},
  "degen_score": 1-5,
  "options_plays": [
    {{
      "ticker": "{dossier['ticker']}",
      "direction": "bullish|bearish|neutral|volatility",
      "strategy_type": "debit_call_spread|credit_put_spread|iron_condor|long_strangle|calendar_call|diagonal_call|jade_lizard|risk_reversal|...",
      "structure": "human-readable legs summary",
      "strike_zone": "e.g. $150/$155 call debit spread",
      "expiry": "YYYY-MM-DD or near→far",
      "legs": [{{"action":"buy|sell","option_type":"call|put","strike":"150","expiry":"YYYY-MM-DD","quantity":1}}],
      "thesis": "why this trade expresses the narrative",
      "edge": "why this structure beats a naked call/put here",
      "iv_note": "IV regime note",
      "max_loss": "string", "max_gain": "string", "breakeven": "string",
      "when_it_wins": "string", "when_it_loses": "string",
      "degen_score": 1-5,
      "risk_note": "what can go wrong"
    }}
  ],
  "sources": [{{"title": "string", "url": "string", "source_type": "news|reddit|catalyst|web"}}]
}}"""


# ---------------------------------------------------------------------------
# Stage 2 — editor pass: summary, sports angles, radar, ranking.
# ---------------------------------------------------------------------------

EDITOR_SYSTEM_PROMPT = """You are the editor of a daily market + sports research briefing.
You receive finished per-ticker deep dives (do NOT rewrite them), a market
dashboard, and a sports research packet.

Hard rules:
- Output ONLY valid JSON matching the schema exactly.
- summary: 2-4 sentences a trader reads first — the day's dominant theme(s),
  what changed overnight, and which deep dives matter most. Reference the
  market tape when it is relevant.
- Sports angles must reference a matchup present in ranked_odds_events.
  When engine_bet_decisions exist, build angles around those picks first:
  state the decision (selection, market, price, stake) in line_note, then
  the story, then what would confirm or invalidate the number. Take a
  stance — the reader wants a decision, not a survey.
  A "lean" is a real setup (positive EV that missed a secondary gate) —
  cover the best leans as actionable angles rather than skipping them.
  Reserve empty sports_angles for slates with no positive-EV outcomes.
- Do NOT invent matchups, odds, injuries, or public-vs-sharp claims.
- radar: single-source or still-forming tickers worth watching, with a
  specific note on what confirmation to wait for.
- This is entertainment/research, not financial advice."""


def build_editor_prompt(
    narrative_digests: list[dict[str, Any]],
    dashboard: dict[str, Any] | None,
    sports_packet: dict[str, Any],
    radar_candidates: list[dict[str, Any]],
) -> str:
    payload = {
        "deep_dives": narrative_digests,
        "market_dashboard": dashboard or {},
        "radar_candidates": radar_candidates,
    }
    return f"""Compose today's briefing shell around these finished deep dives.

STOCK CONTEXT:
{json.dumps(payload, indent=2, default=str)}

SPORTS RESEARCH PACKET:
{json.dumps(sports_packet, indent=2, default=str)}

Return JSON with this exact structure:
{{
  "summary": "2-4 sentence editor's overview of the day",
  "narrative_order": ["deep dive titles, strongest story first"],
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
      "confirmation_points": ["..."],
      "invalidation_points": ["..."],
      "degen_score": 1-5,
      "sources": [{{"title": "string", "url": "string", "source_type": "news|reddit|odds|web"}}]
    }}
  ],
  "radar": [
    {{"ticker": "TICK", "buzz_delta": 0.0, "mention_count": 0, "note": "what to watch for"}}
  ]
}}

Produce 2-4 sports angles (when events exist) and 3-8 radar items.
A "lean" engine decision is a real setup — cover the best leans as actionable
angles (with the caveat that they missed the full bet bar) rather than skipping
them. Reserve an empty sports_angles list for slates with no positive-EV outcomes."""


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


async def _call_llm_json(
    client: AsyncOpenAI,
    *,
    system: str,
    user: str,
    use_web: bool,
    max_tool_calls: int | None = None,
    max_tokens: int = 6000,
) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    """One JSON-object completion with graceful degradation:
    Responses+web -> Responses -> chat completions. Returns (data, web
    citations, api mode)."""
    if hasattr(client, "responses"):
        web_attempts = [True, False] if (use_web and settings.openai_use_web_search) else [False]
        for attempt_web in web_attempts:
            tools = []
            if attempt_web:
                tools.append(
                    {
                        "type": "web_search",
                        "search_context_size": settings.openai_web_search_context,
                    }
                )
            try:
                response = await client.responses.create(
                    model=settings.openai_model,
                    instructions=system,
                    input=user,
                    tools=tools,
                    max_tool_calls=max_tool_calls or settings.openai_max_tool_calls,
                    text={"format": {"type": "json_object"}},
                    **responses_tuning(
                        settings.openai_model,
                        temperature=0.45,
                        reasoning_effort=settings.openai_reasoning_effort,
                    ),
                )
            except Exception as exc:
                logger.warning("Responses API call failed (web=%s): %s", attempt_web, exc)
                continue

            raw = _extract_response_text(response)
            if not raw:
                logger.warning(
                    "Responses API returned empty text (status=%s, web=%s)",
                    getattr(response, "status", "unknown"),
                    attempt_web,
                )
                continue
            try:
                data = _parse_model_json(raw)
            except ValueError as exc:
                logger.warning("Responses JSON invalid (web=%s): %s", attempt_web, exc)
                continue
            return data, _extract_citations(response), (
                "responses_web" if attempt_web else "responses"
            )

        logger.warning("Responses API produced no parseable JSON; falling back to chat completions")

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        **chat_tuning(settings.openai_model, temperature=0.45, max_tokens=max_tokens),
    )
    raw = response.choices[0].message.content or "{}"
    return _parse_model_json(raw), [], "chat_completions"


def select_deep_dive_dossiers(
    dossiers: list[dict[str, Any]],
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Confirmed-tier dossiers first, then developing ones with real news, up
    to `limit`. Watch-tier chatter never gets a deep dive — it goes to radar."""
    selected = [
        d
        for d in dossiers
        if (d.get("research_quality") or {}).get("conviction_tier") == TIER_CONFIRMED
    ][:limit]
    if len(selected) < limit:
        for d in dossiers:
            if len(selected) >= limit:
                break
            quality = d.get("research_quality") or {}
            if (
                quality.get("conviction_tier") == TIER_DEVELOPING
                and quality.get("news_domain_count", 0) >= 1
                and d not in selected
            ):
                selected.append(d)
    return selected


def _narrative_digest(narrative: dict[str, Any]) -> dict[str, Any]:
    quality = narrative.get("research_quality") or {}
    return {
        "title": narrative.get("title", ""),
        "tickers": narrative.get("tickers", []),
        "conviction_tier": quality.get("conviction_tier"),
        "degen_score": narrative.get("degen_score"),
        "story": str(narrative.get("story", ""))[:400],
        "insight": str(narrative.get("insight", ""))[:300],
        "top_play": (narrative.get("options_plays") or [{}])[0].get("strategy_type", ""),
    }


async def generate_llm_briefing(
    client: AsyncOpenAI,
    *,
    dossiers: list[dict[str, Any]],
    ongoing_narratives: list[dict[str, Any]],
    macro_context: list[dict[str, Any]] | None,
    sports_packet: dict[str, Any],
    market_dashboard: dict[str, Any] | None,
    report: RunReportBuilder | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    """Two-stage synthesis. Returns (briefing data, citations, api mode)."""
    threads_by_ticker = {t.get("ticker", ""): t for t in ongoing_narratives or []}

    deep_dive_dossiers = select_deep_dive_dossiers(dossiers)

    async def deep_dive(
        dossier: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]], str]:
        prompt = build_deep_dive_prompt(
            dossier, threads_by_ticker.get(dossier["ticker"]), macro_context
        )
        try:
            data, citations, mode = await _call_llm_json(
                client,
                system=DEEP_DIVE_SYSTEM_PROMPT,
                user=prompt,
                use_web=True,
                max_tool_calls=6,
            )
        except Exception as exc:
            logger.warning("Deep dive failed for %s: %s", dossier["ticker"], exc)
            return None, [], "failed"
        if not data.get("title") or not data.get("tickers"):
            return None, citations, mode
        return data, citations, mode

    results = await asyncio.gather(*(deep_dive(d) for d in deep_dive_dossiers))
    narratives: list[dict[str, Any]] = []
    citations: list[dict[str, str]] = []
    modes: set[str] = set()
    for data, dive_citations, mode in results:
        if data is not None:
            narratives.append(data)
            citations.extend(dive_citations)
            modes.add(mode)

    if report is not None:
        report.stage(
            "deep_dives",
            attempted=[d["ticker"] for d in deep_dive_dossiers],
            produced=len(narratives),
        )

    # Radar candidates for the editor: everything that didn't get a deep dive
    dived = {d["ticker"] for d in deep_dive_dossiers}
    radar_candidates = [
        {
            "ticker": d["ticker"],
            "buzz_delta": d.get("buzz_delta", 0.0),
            "mention_count": d.get("mention_count", 0),
            "candidate_sources": d.get("candidate_sources", []),
            "news_domain_count": (d.get("research_quality") or {}).get("news_domain_count", 0),
            "top_source": (d.get("sources") or [{}])[0].get("title", ""),
        }
        for d in dossiers
        if d["ticker"] not in dived
    ][:10]

    editor_prompt = build_editor_prompt(
        [_narrative_digest(n) for n in narratives],
        market_dashboard,
        sports_packet,
        radar_candidates,
    )
    try:
        editor_data, editor_citations, editor_mode = await _call_llm_json(
            client,
            system=EDITOR_SYSTEM_PROMPT,
            user=editor_prompt,
            use_web=False,
            max_tokens=4000,
        )
        citations.extend(editor_citations)
        modes.add(editor_mode)
    except Exception as exc:
        logger.warning("Editor pass failed, composing shell deterministically: %s", exc)
        editor_data = {}

    # Apply the editor's ranking without letting it rewrite the deep dives
    order = {
        str(title): idx
        for idx, title in enumerate(editor_data.get("narrative_order") or [])
    }
    if order:
        narratives.sort(key=lambda n: order.get(n.get("title", ""), len(order)))

    summary = str(editor_data.get("summary") or "").strip()
    if not summary:
        tickers_line = ", ".join(n["tickers"][0] for n in narratives if n.get("tickers"))
        summary = (
            f"{len(narratives)} multi-source stories today: {tickers_line}."
            if narratives
            else "No multi-source stories today."
        )

    api_mode = "+".join(sorted(modes)) if modes else "none"
    return (
        {
            "summary": summary,
            "narratives": narratives,
            "sports_angles": editor_data.get("sports_angles") or [],
            "radar": editor_data.get("radar") or [],
        },
        citations,
        api_mode,
    )


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
    dossiers: list[dict[str, Any]] | None = None,
    ongoing_narratives: list[dict[str, Any]] | None = None,
    market_dashboard: dict[str, Any] | None = None,
    report: RunReportBuilder | None = None,
) -> BriefingContent:
    # Prefer the caller's universe-validated watchlist; fall back to raw counts
    if top_tickers is None:
        top_tickers = select_top_tickers(ticker_counts)
    if dossiers is None:
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
    if report is not None:
        report.set("dossier_verdicts", dossier_verdicts(dossiers))

    sports_packet = build_sports_research_packet(
        sports_posts, odds, sports_news, bet_decisions=sports_bet_decisions
    )

    if settings.openai_api_key:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        data, citations, api_mode = await generate_llm_briefing(
            client,
            dossiers=dossiers,
            ongoing_narratives=ongoing_narratives or [],
            macro_context=macro_context,
            sports_packet=sports_packet,
            market_dashboard=market_dashboard,
            report=report,
        )
    else:
        logger.warning("OPENAI_API_KEY missing — producing deterministic data digest")
        data = build_deterministic_briefing(
            dossiers,
            dashboard=market_dashboard,
            ongoing_narratives=ongoing_narratives or [],
        )
        citations, api_mode = [], "deterministic"

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

    raw_narratives = data.get("narratives") or []
    before_count = len(raw_narratives)
    data["narratives"], dropped_reasons = validate_narratives(
        raw_narratives,
        dossiers,
        require_multi_source=settings.require_multi_source_narratives,
        options=options,
    )
    tier_counts: dict[str, int] = {}
    for narrative in data["narratives"]:
        tier = (narrative.get("research_quality") or {}).get("conviction_tier", "watch")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    low_confidence_count = sum(
        1
        for n in data["narratives"]
        if not (n.get("research_quality") or {}).get("meets_multi_source_bar", False)
    )
    if report is not None:
        report.set("raw_narrative_count", before_count)
        report.set("validated_narrative_count", len(data["narratives"]))
        report.set("narratives_dropped", dropped_reasons)
        report.set("narrative_tiers", tier_counts)
        report.set("low_confidence_narratives", low_confidence_count)
        report.set("llm_api_mode", api_mode)
        report.set("web_citations", len(citations))

    # Auto-radar for strong-buzz tickers that failed the multi-source bar
    narrative_tickers = {
        str(t).upper() for n in data["narratives"] for t in (n.get("tickers") or [])
    }
    radar = list(data.get("radar") or [])
    radar_tickers = {str(r.get("ticker", "")).upper() for r in radar}
    for dossier in dossiers:
        t = dossier["ticker"]
        quality = dossier.get("research_quality") or {}
        if quality.get("meets_multi_source_bar") or t in narrative_tickers:
            continue
        if t in radar_tickers:
            continue
        if dossier.get("mention_count", 0) < 2 and not dossier.get("candidate_sources"):
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

    data["market_dashboard"] = market_dashboard or {}

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
        "narrative_tiers": tier_counts,
    }
    data["research_metadata"] = {
        "model": settings.openai_model if api_mode != "deterministic" else "deterministic",
        "api_mode": api_mode,
        "web_search_enabled": "responses_web" in api_mode,
        "synthesis_pipeline": "deep-dive+editor-v3",
        "validated_sports_angles": len(sports_angles),
        "briefing_news_max_age_hours": settings.briefing_news_max_age_hours,
        "min_independent_sources": settings.min_independent_sources,
        "require_multi_source_narratives": settings.require_multi_source_narratives,
        "strategy_engine": "strategies-v2",
    }
    return BriefingContent.model_validate(data)
