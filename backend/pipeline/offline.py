"""Deterministic briefing builder — no LLM required.

Used when OPENAI_API_KEY is missing (and by backfills in keyless
environments). Produces an honest data digest from the research dossiers:
corroborated claims, source lists, options context, and the deterministic
strategy engine's candidates. It never invents synthesis — narrative
`insight` fields state that cross-source synthesis needs the LLM.
"""

from __future__ import annotations

from typing import Any

from pipeline.research import TIER_CONFIRMED, TIER_DEVELOPING


def _narrative_from_dossier(
    dossier: dict[str, Any],
    threads_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    ticker = dossier["ticker"]
    quality = dossier.get("research_quality") or {}
    sources = dossier.get("sources") or []
    news_sources = [s for s in sources if s.get("source_type") in {"news", "catalyst"}]
    if not news_sources:
        return None

    claims = dossier.get("corroborated_claims") or []
    top_claim = claims[0]["claim"] if claims else news_sources[0]["title"]

    coverage_bits = []
    seen_domains: set[str] = set()
    for s in news_sources[:4]:
        domain = s.get("domain") or s.get("source") or ""
        if domain in seen_domains:
            continue
        seen_domains.add(domain)
        coverage_bits.append(f"{s.get('source') or domain}: “{s['title']}”")
    story = " · ".join(coverage_bits)

    opts = dossier.get("options") or {}
    why_bits = []
    age = quality.get("newest_source_age_hours")
    if age is not None:
        why_bits.append(f"newest source {age:g}h old")
    if opts.get("pct_change") is not None:
        why_bits.append(f"stock {opts['pct_change']:+.1f}% on the day")
    if opts.get("iv_rank") is not None:
        why_bits.append(f"IV rank {round(opts['iv_rank'] * 100)}")
    if dossier.get("mention_count"):
        why_bits.append(f"{dossier['mention_count']} Reddit mention(s)")
    why_now = "; ".join(why_bits) or "Fresh multi-source coverage today"

    priced_bits = []
    if opts.get("iv_regime"):
        priced_bits.append(f"IV regime: {opts['iv_regime']}")
    if opts.get("put_call_volume_ratio") is not None:
        priced_bits.append(f"put/call volume {opts['put_call_volume_ratio']}")
    if opts.get("call_put_iv_skew") is not None:
        priced_bits.append(f"put-call IV skew {opts['call_put_iv_skew']:+.1%}")

    plays = list(dossier.get("strategy_candidates") or [])[:2]
    direction = plays[0]["direction"] if plays else ""

    thread = threads_by_ticker.get(ticker)
    thread_update = {
        "status": "continuing" if thread else "new",
        "what_changed": f"Data-digest update: {top_claim[:160]}" if thread else "",
    }

    sources_out = [
        {
            "title": s["title"],
            "url": s.get("url", ""),
            "source_type": s.get("source_type", "news"),
        }
        for s in news_sources[:5]
        if s.get("url")
    ]

    return {
        "title": f"{ticker}: {top_claim[:110]}",
        "tickers": [ticker],
        "story": story,
        "why_now": why_now,
        "insight": (
            "Deterministic data digest (no LLM synthesis): "
            f"{quality.get('news_domain_count', 0)} independent news domain(s), "
            f"{quality.get('corroborated_claim_count', 0)} corroborated claim cluster(s). "
            "Verify the cited sources before acting."
        ),
        "priced_in": "; ".join(priced_bits),
        "bull_case": (
            f"Coverage follow-through on: {top_claim[:140]}"
            if direction != "bearish"
            else "Story fades and the market shrugs it off"
        ),
        "bear_case": (
            f"Story fades / gets walked back: {top_claim[:120]}"
            if direction != "bearish"
            else f"Downside follow-through on: {top_claim[:130]}"
        ),
        "catalysts": [c.get("headline", "")[:120] for c in (dossier.get("catalysts") or [])[:3]],
        "confirmation_points": ["Additional independent outlets pick up the story"],
        "invalidation_points": ["Primary source retracts or contradicting coverage appears"],
        "thread_update": thread_update,
        "degen_score": 3,
        "options_plays": plays,
        "sources": sources_out,
    }


def build_deterministic_briefing(
    dossiers: list[dict[str, Any]],
    *,
    dashboard: dict[str, Any] | None = None,
    ongoing_narratives: list[dict[str, Any]] | None = None,
    max_narratives: int = 5,
) -> dict[str, Any]:
    threads_by_ticker = {t.get("ticker", ""): t for t in ongoing_narratives or []}

    narratives: list[dict[str, Any]] = []
    used: set[str] = set()
    for dossier in dossiers:
        if len(narratives) >= max_narratives:
            break
        tier = (dossier.get("research_quality") or {}).get("conviction_tier")
        if tier not in {TIER_CONFIRMED, TIER_DEVELOPING}:
            continue
        narrative = _narrative_from_dossier(dossier, threads_by_ticker)
        if narrative:
            narratives.append(narrative)
            used.add(dossier["ticker"])

    radar = []
    for dossier in dossiers:
        if dossier["ticker"] in used:
            continue
        if dossier.get("mention_count", 0) < 1 and not dossier.get("sources"):
            continue
        quality = dossier.get("research_quality") or {}
        if quality.get("meets_multi_source_bar"):
            note = (
                f"Well-sourced ({quality.get('news_domain_count', 0)} news domains) — "
                "cut for narrative count, still worth a look"
            )
        else:
            note = (
                f"{quality.get('independent_source_count', 0)} independent source(s), "
                f"{quality.get('news_domain_count', 0)} news domain(s) — "
                "not enough for a full story yet"
            )
        radar.append(
            {
                "ticker": dossier["ticker"],
                "buzz_delta": dossier.get("buzz_delta", 0.0),
                "mention_count": dossier.get("mention_count", 0),
                "note": note,
            }
        )

    summary_bits: list[str] = []
    for idx in (dashboard or {}).get("indices", [])[:3]:
        summary_bits.append(f"{idx['symbol']} {idx['pct_change']:+.1f}%")
    tape = ", ".join(summary_bits)
    linked = sum(1 for n in narratives if len(n.get("sources", [])) >= 2)
    tickers_line = ", ".join(n["tickers"][0] for n in narratives) or "no tickers"
    summary = (
        (f"Tape: {tape}. " if tape else "")
        + f"Deterministic digest of {len(narratives)} sourced stories ({tickers_line}); "
        f"{linked} with 2+ cited links. LLM synthesis was unavailable for this run — "
        "narratives are data digests with engine-generated options structures."
    )

    return {
        "summary": summary,
        "narratives": narratives,
        "sports_angles": [],
        "radar": radar[:10],
    }
