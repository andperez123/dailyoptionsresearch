"""Render a BriefingContent to a readable markdown report."""

from __future__ import annotations

from datetime import date
from typing import Any

from models import BriefingContent


def _pct(value: Any) -> str:
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _dashboard_md(dashboard: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    indices = dashboard.get("indices") or []
    if indices:
        tape = " · ".join(
            f"**{i['symbol']}** {i.get('price', '—')} ({_pct(i.get('pct_change'))})" for i in indices
        )
        lines += ["## Market dashboard", "", tape, ""]

    movers = dashboard.get("watchlist_movers") or []
    if movers:
        lines += ["**Watchlist movers**", ""]
        lines += [
            f"- {m['ticker']}: {_pct(m.get('pct_change'))}"
            + (f" (${m['price']})" if m.get("price") else "")
            for m in movers
        ]
        lines.append("")

    iv = dashboard.get("iv_extremes") or []
    if iv:
        lines += ["**IV extremes**", ""]
        lines += [
            f"- {x['ticker']}: IV rank {round((x.get('iv_rank') or 0) * 100)} — {x.get('read', '')}"
            for x in iv
        ]
        lines.append("")

    flow = dashboard.get("unusual_flow") or []
    if flow:
        lines += ["**Unusual options flow**", ""]
        lines += [
            f"- {x['ticker']}: put/call {x.get('put_call_ratio')} — {x.get('read', '')}" for x in flow
        ]
        lines.append("")

    earnings = dashboard.get("earnings_ahead") or []
    if earnings:
        lines += ["**Earnings ahead**", ""]
        lines += [f"- {e['ticker']} — {e['date']}" for e in earnings]
        lines.append("")

    buzz = dashboard.get("buzz_leaders") or []
    if buzz:
        lines += ["**Buzz leaders**", ""]
        lines += [
            f"- {b['ticker']}: z {b.get('buzz_z')} on {b.get('mentions')} mention(s)" for b in buzz
        ]
        lines.append("")
    return lines


def briefing_to_markdown(briefing_date: date, content: BriefingContent) -> str:
    lines: list[str] = [f"# Daily briefing — {briefing_date.isoformat()}", ""]

    meta = content.research_metadata or {}
    if meta.get("api_mode"):
        lines += [f"*Synthesis: {meta.get('model', '?')} ({meta['api_mode']})*", ""]

    lines += ["## Summary", "", content.summary, ""]

    lines += _dashboard_md(content.market_dashboard or {})

    if content.narratives:
        lines += ["## Narratives", ""]
    for n in content.narratives:
        quality = n.research_quality or {}
        tier = quality.get("conviction_tier", "watch")
        tickers = ", ".join(f"${t}" for t in n.tickers)
        lines += [f"### {n.title}", ""]
        lines += [
            f"*{tickers} · tier: **{tier}** · "
            f"{quality.get('independent_source_count', 0)} independent source(s) · "
            f"degen {n.degen_score}/5*",
            "",
        ]
        if n.story:
            lines += [n.story, ""]
        if n.insight:
            lines += [f"**Insight:** {n.insight}", ""]
        if n.why_now:
            lines += [f"**Why now:** {n.why_now}", ""]
        if n.priced_in:
            lines += [f"**Priced in:** {n.priced_in}", ""]
        lines += [f"**Bull:** {n.bull_case}", "", f"**Bear:** {n.bear_case}", ""]
        if n.catalysts:
            lines += ["**Catalysts:** " + "; ".join(n.catalysts), ""]
        if n.options_plays:
            lines += ["**Options structures:**", ""]
            for p in n.options_plays:
                play = p if isinstance(p, dict) else p.model_dump()
                bits = [
                    f"{play.get('ticker', '')} {str(play.get('strategy_type', play.get('direction', ''))).replace('_', ' ')}",
                    play.get("structure") or play.get("strike_zone") or "",
                    play.get("expiry") or "",
                ]
                lines.append("- " + " · ".join(b for b in bits if b))
                if play.get("thesis"):
                    lines.append(f"  - Thesis: {play['thesis']}")
                if play.get("edge"):
                    lines.append(f"  - Edge: {play['edge']}")
                if play.get("risk_note"):
                    lines.append(f"  - Risk: {play['risk_note']}")
            lines.append("")
        if n.sources:
            lines += ["**Sources:**", ""]
            for s in n.sources:
                source = s if isinstance(s, dict) else s.model_dump()
                title = source.get("title", "source")
                url = source.get("url", "")
                lines.append(f"- [{title}]({url})" if url else f"- {title}")
            lines.append("")

    if content.radar:
        lines += ["## Radar", ""]
        for r in content.radar:
            item = r if isinstance(r, dict) else r.model_dump()
            lines.append(
                f"- **{item.get('ticker')}** — {item.get('note', '')} "
                f"(buzz z {item.get('buzz_delta', 0)}, {item.get('mention_count', 0)} mentions)"
            )
        lines.append("")

    stats = content.raw_stats or {}
    if stats:
        lines += [
            "---",
            "",
            f"*{stats.get('news_items_collected', 0)} news items · "
            f"{stats.get('ticker_dossiers', 0)} dossiers · "
            f"{stats.get('multi_source_dossiers', 0)} multi-source · "
            f"tiers {stats.get('narrative_tiers', {})}*",
            "",
        ]
    return "\n".join(lines)
