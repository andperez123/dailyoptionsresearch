"""Multi-source research dossiers, corroboration, and freshness gates."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from config import settings
from pipeline.news import NewsItem
from pipeline.options import OptionsSnapshot
from pipeline.reddit import RedditPost
from pipeline.strategies import propose_strategies, proposals_to_play_dicts
from time_utils import parse_rss_datetime, utc_now


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _parse_published(value: str | datetime | None) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=utc_now().tzinfo)
    try:
        return parse_rss_datetime(value)
    except Exception:
        return None


def _is_fresh(published: str | datetime | None, max_age_hours: int) -> bool:
    dt = _parse_published(published)
    if dt is None:
        return True
    now = utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now.tzinfo)
    return (now - dt) <= timedelta(hours=max_age_hours)


def _normalize_claim_key(text: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", text.lower()).split()
    stop = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "after", "as"}
    keep = [w for w in words if w not in stop and len(w) > 2]
    return " ".join(sorted(set(keep))[:8])


def build_ticker_dossiers(
    tickers: list[str],
    news: list[NewsItem],
    finance_posts: list[RedditPost],
    options: list[OptionsSnapshot],
    overnight_catalysts: list[dict[str, Any]],
    ticker_counts: dict[str, int],
    buzz_deltas: dict[str, float],
    macro_context: list[dict[str, Any]] | None = None,
    max_age_hours: int | None = None,
) -> list[dict[str, Any]]:
    """Build per-ticker multi-source research packets with corroboration metrics."""
    max_age = max_age_hours if max_age_hours is not None else settings.briefing_news_max_age_hours
    options_by_ticker = {o.ticker.upper(): o for o in options}
    dossiers: list[dict[str, Any]] = []

    news_by_ticker: dict[str, list[NewsItem]] = defaultdict(list)
    for item in news:
        if not _is_fresh(item.published, max_age):
            continue
        related = []
        if item.ticker:
            related.append(item.ticker.upper())
        # Also attach if ticker appears in title for watchlist names
        title_upper = item.title.upper()
        for t in tickers:
            if t.upper() in title_upper or f"${t.upper()}" in title_upper:
                related.append(t.upper())
        for t in set(related):
            if t in {x.upper() for x in tickers}:
                news_by_ticker[t].append(item)

    posts_by_ticker: dict[str, list[RedditPost]] = defaultdict(list)
    for post in finance_posts:
        blob = f"{post.title} {post.selftext or ''}".upper()
        for t in tickers:
            if re.search(rf"\${t.upper()}\b|\b{t.upper()}\b", blob):
                posts_by_ticker[t.upper()].append(post)

    cats_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cat in overnight_catalysts:
        primary = (cat.get("primary_ticker") or "").upper()
        related = [str(x).upper() for x in cat.get("related_tickers") or []]
        for t in {primary, *related}:
            if t and t in {x.upper() for x in tickers}:
                cats_by_ticker[t].append(cat)

    for ticker in tickers:
        t = ticker.upper()
        sources: list[dict[str, Any]] = []
        claim_map: dict[str, dict[str, Any]] = {}

        for item in news_by_ticker.get(t, [])[:12]:
            domain = _domain(item.url) or item.source or "news"
            source_type = getattr(item, "source_tier", None) or "news"
            if source_type == "rss":
                source_type = "news"
            summary = getattr(item, "summary", "") or ""
            entry = {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "domain": domain,
                "source_type": source_type if source_type != "finnhub" else "news",
                "provider": source_type,
                "published": item.published,
                "summary": summary[:500] if summary and summary != item.title else "",
            }
            sources.append(entry)
            key = _normalize_claim_key(item.title)
            if key:
                bucket = claim_map.setdefault(
                    key,
                    {"claim": item.title, "domains": set(), "urls": [], "count": 0},
                )
                bucket["domains"].add(domain)
                bucket["urls"].append(item.url)
                bucket["count"] += 1

        for post in posts_by_ticker.get(t, [])[:6]:
            sources.append(
                {
                    "title": post.title,
                    "url": post.url,
                    "source": f"r/{post.subreddit}",
                    "domain": "reddit.com",
                    "source_type": "reddit",
                    "provider": "reddit",
                    "published": "",
                    "summary": (post.selftext or "")[:400],
                    "score": post.score,
                }
            )

        for cat in cats_by_ticker.get(t, [])[:6]:
            sources.append(
                {
                    "title": cat.get("headline") or cat.get("thesis") or "catalyst",
                    "url": cat.get("source_url") or "",
                    "source": cat.get("source_name") or "catalyst",
                    "domain": _domain(cat.get("source_url") or "") or "catalyst",
                    "source_type": "catalyst",
                    "provider": cat.get("source_name") or "catalyst",
                    "published": cat.get("published_at") or cat.get("detected_at") or "",
                    "summary": cat.get("summary") or cat.get("thesis") or "",
                    "impact_score": cat.get("impact_score"),
                    "direction": cat.get("direction"),
                    "supporting_source_count": cat.get("supporting_source_count"),
                }
            )
            key = _normalize_claim_key(cat.get("headline") or cat.get("thesis") or "")
            if key:
                bucket = claim_map.setdefault(
                    key,
                    {
                        "claim": cat.get("headline") or cat.get("thesis"),
                        "domains": set(),
                        "urls": [],
                        "count": 0,
                    },
                )
                bucket["domains"].add(_domain(cat.get("source_url") or "") or "catalyst")
                if cat.get("source_url"):
                    bucket["urls"].append(cat["source_url"])
                bucket["count"] += int(cat.get("supporting_source_count") or 1)

        # Independent = distinct domains excluding empty, plus distinct source_types
        domains = {s["domain"] for s in sources if s.get("domain")}
        source_types = {s["source_type"] for s in sources if s.get("source_type")}
        # Reddit alone should not count as multi-source confirmation
        independent_news_domains = {
            d for d in domains if d not in {"", "reddit.com", "catalyst"}
        }
        independent_source_count = len(independent_news_domains) + (
            1 if "reddit" in source_types else 0
        ) + (1 if "catalyst" in source_types and independent_news_domains else 0)

        corroborated_claims = []
        for bucket in claim_map.values():
            domain_count = len(bucket["domains"])
            if domain_count >= 2 or bucket["count"] >= 2:
                corroborated_claims.append(
                    {
                        "claim": bucket["claim"],
                        "independent_domains": sorted(bucket["domains"]),
                        "domain_count": domain_count,
                        "mention_count": bucket["count"],
                        "urls": bucket["urls"][:4],
                    }
                )
        corroborated_claims.sort(key=lambda c: (-c["domain_count"], -c["mention_count"]))

        opt = options_by_ticker.get(t)
        top_cat = cats_by_ticker.get(t, [{}])[0] if cats_by_ticker.get(t) else {}
        strategy_candidates: list[dict[str, Any]] = []
        options_context: dict[str, Any] = {}
        if opt and not opt.error:
            options_context = {
                "price": opt.current_price,
                "nearest_expiry": opt.nearest_expiry,
                "next_expiry": getattr(opt, "next_expiry", None),
                "avg_iv": opt.avg_iv,
                "put_call_volume_ratio": opt.put_call_volume_ratio,
                "iv_regime": getattr(opt, "iv_regime", None),
                "atm_iv": getattr(opt, "atm_iv", None),
                "iv_rank": getattr(opt, "iv_rank", None),
                "realized_vol_20d": getattr(opt, "realized_vol_20d", None),
                "call_put_iv_skew": getattr(opt, "call_put_iv_skew", None),
                "pct_change": getattr(opt, "pct_change", None),
            }
            proposals = propose_strategies(
                ticker=t,
                price=opt.current_price,
                nearest_expiry=opt.nearest_expiry,
                next_expiry=getattr(opt, "next_expiry", None),
                avg_iv=opt.avg_iv,
                put_call_ratio=opt.put_call_volume_ratio,
                pct_change=getattr(opt, "pct_change", None),
                catalyst_direction=top_cat.get("direction"),
                catalyst_type=top_cat.get("catalyst_type"),
                half_life=top_cat.get("half_life"),
                limit=3,
                atm_iv=getattr(opt, "atm_iv", None),
                iv_rank=getattr(opt, "iv_rank", None),
                realized_vol=getattr(opt, "realized_vol_20d", None),
                iv_skew=getattr(opt, "call_put_iv_skew", None),
                chains=getattr(opt, "chains", None),
                min_leg_open_interest=settings.options_min_leg_open_interest,
                max_leg_spread_pct=settings.options_max_leg_spread_pct,
            )
            strategy_candidates = proposals_to_play_dicts(proposals)

        freshness_hours = []
        for s in sources:
            dt = _parse_published(s.get("published"))
            if dt:
                now = utc_now()
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=now.tzinfo)
                freshness_hours.append(round((now - dt).total_seconds() / 3600, 1))
        newest_hours = min(freshness_hours) if freshness_hours else None

        research_quality = {
            "independent_source_count": independent_source_count,
            "distinct_domains": sorted(domains)[:12],
            "source_types": sorted(source_types),
            "news_domain_count": len(independent_news_domains),
            "corroborated_claim_count": len(corroborated_claims),
            "newest_source_age_hours": newest_hours,
            "meets_multi_source_bar": independent_source_count
            >= settings.min_independent_sources
            and len(independent_news_domains) >= 1,
            "max_age_hours_applied": max_age,
        }

        dossiers.append(
            {
                "ticker": t,
                "mention_count": ticker_counts.get(t, ticker_counts.get(ticker, 0)),
                "buzz_delta": buzz_deltas.get(t, buzz_deltas.get(ticker, 0.0)),
                "sources": sources[:20],
                "corroborated_claims": corroborated_claims[:5],
                "catalysts": cats_by_ticker.get(t, [])[:5],
                "options": options_context,
                "strategy_candidates": strategy_candidates,
                "research_quality": research_quality,
                "macro_context": macro_context or [],
            }
        )

    # Rank dossiers: multi-source + corroboration first, then buzz
    dossiers.sort(
        key=lambda d: (
            -int(d["research_quality"]["meets_multi_source_bar"]),
            -d["research_quality"]["corroborated_claim_count"],
            -d["research_quality"]["independent_source_count"],
            -d.get("mention_count", 0),
        )
    )
    return dossiers


_WEAK_STRATEGY_TYPES = {
    "call",
    "put",
    "long_call",
    "long_put",
    "directional_calls",
    "directional_puts",
    "",
}


def _legs_match_chain(play: dict[str, Any], snapshot: OptionsSnapshot | None) -> bool:
    """True when every leg of a model-proposed play references a listed
    strike/expiry/side in the fetched chain. Plays without legs, or tickers
    without chain data, can't be checked and pass by default."""
    legs = play.get("legs") or []
    if not legs:
        return True
    chains = getattr(snapshot, "chains", None) if snapshot else None
    if not chains:
        return True
    for leg in legs:
        expiry = str(leg.get("expiry", ""))[:10]
        chain = chains.get(expiry)
        if chain is None:
            return False
        action = leg.get("action")
        option_type = leg.get("option_type")
        if action not in {"buy", "sell"} or option_type not in {"call", "put"}:
            return False
        try:
            strike = float(leg.get("strike"))
        except (TypeError, ValueError):
            return False
        matched = next(
            (sides for listed, sides in chain.items() if abs(strike - listed) < 0.01),
            None,
        )
        if not matched or not matched.get(option_type):
            return False
    return True


def _play_is_weak(play: dict[str, Any], snapshot: OptionsSnapshot | None) -> bool:
    strategy = str(play.get("strategy_type", play.get("direction", ""))).lower()
    if strategy in _WEAK_STRATEGY_TYPES:
        return True
    return not _legs_match_chain(play, snapshot)


def dossier_verdicts(dossiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact per-ticker pass/fail summary for the run report, with a
    human-readable reason when a ticker failed the multi-source bar."""
    verdicts: list[dict[str, Any]] = []
    for d in dossiers:
        quality = d.get("research_quality") or {}
        meets = bool(quality.get("meets_multi_source_bar"))
        news_domains = quality.get("news_domain_count", 0)
        independent = quality.get("independent_source_count", 0)
        source_types = quality.get("source_types") or []
        if meets:
            reason = ""
        elif not d.get("sources"):
            reason = "No sources found (no fresh news, Reddit posts, or catalysts)"
        elif news_domains == 0:
            reason = (
                "Only Reddit/catalyst chatter — no independent news domain within "
                f"{quality.get('max_age_hours_applied', '?')}h"
                if source_types
                else "No fresh news within the freshness window"
            )
        else:
            reason = (
                f"Only {independent} independent source(s); "
                f"{settings.min_independent_sources} required"
            )
        verdicts.append(
            {
                "ticker": d["ticker"],
                "mention_count": d.get("mention_count", 0),
                "buzz_delta": d.get("buzz_delta", 0.0),
                "source_count": len(d.get("sources") or []),
                "independent_source_count": independent,
                "news_domain_count": news_domains,
                "source_types": source_types,
                "corroborated_claim_count": quality.get("corroborated_claim_count", 0),
                "newest_source_age_hours": quality.get("newest_source_age_hours"),
                "strategy_candidates": len(d.get("strategy_candidates") or []),
                "meets_multi_source_bar": meets,
                "fail_reason": reason,
            }
        )
    return verdicts


def validate_narratives(
    narratives: list[dict[str, Any]],
    dossiers: list[dict[str, Any]],
    *,
    require_multi_source: bool | None = None,
    options: list[OptionsSnapshot] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach research_quality, prefer multi-source, drop single-source weak
    theses. Returns (kept, dropped) where each dropped entry records the
    title, tickers, and the reason it was rejected."""
    hard_gate = (
        settings.require_multi_source_narratives
        if require_multi_source is None
        else require_multi_source
    )
    dossier_by_ticker = {d["ticker"]: d for d in dossiers}
    snapshot_by_ticker = {o.ticker.upper(): o for o in options or []}
    validated: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    def _drop(raw: dict[str, Any], reason: str) -> None:
        dropped.append(
            {
                "title": raw.get("title", ""),
                "tickers": [str(t).upper() for t in raw.get("tickers") or []],
                "reason": reason,
            }
        )

    for raw in narratives:
        tickers = [str(t).upper() for t in raw.get("tickers") or []]
        matched = [dossier_by_ticker[t] for t in tickers if t in dossier_by_ticker]
        if not matched:
            raw["research_quality"] = {
                "independent_source_count": 0,
                "meets_multi_source_bar": False,
                "warning": "No matching research dossier for tickers",
            }
            if hard_gate:
                _drop(raw, "No research dossier for its tickers — thesis has no packet support")
                continue
            validated.append(raw)
            continue

        independent = max(d["research_quality"]["independent_source_count"] for d in matched)
        news_domains = set()
        source_types = set()
        corroborated = 0
        for d in matched:
            news_domains.update(
                x
                for x in d["research_quality"].get("distinct_domains", [])
                if x not in {"reddit.com", "catalyst", ""}
            )
            source_types.update(d["research_quality"].get("source_types", []))
            corroborated += d["research_quality"].get("corroborated_claim_count", 0)

        meets = independent >= settings.min_independent_sources and len(news_domains) >= 1
        raw["research_quality"] = {
            "independent_source_count": independent,
            "news_domain_count": len(news_domains),
            "source_types": sorted(source_types),
            "corroborated_claim_count": corroborated,
            "meets_multi_source_bar": meets,
            "dossier_tickers": [d["ticker"] for d in matched],
        }

        existing_urls = {s.get("url") for s in raw.get("sources") or [] if s.get("url")}
        enriched_sources = list(raw.get("sources") or [])
        for d in matched:
            for s in d.get("sources") or []:
                if s.get("url") and s["url"] not in existing_urls and s.get("source_type") != "reddit":
                    enriched_sources.append(
                        {
                            "title": s.get("title", "Source"),
                            "url": s["url"],
                            "source_type": s.get("source_type", "news"),
                        }
                    )
                    existing_urls.add(s["url"])
                if len(enriched_sources) >= 6:
                    break
            if len(enriched_sources) >= 6:
                break
        raw["sources"] = enriched_sources

        # Drop model plays that are naked long options or reference strikes/
        # expiries missing from the real chain; backfill from deterministic
        # strategy candidates so narratives keep an actionable structure.
        plays = raw.get("options_plays") or []
        kept_plays = [
            p
            for p in plays
            if not _play_is_weak(p, snapshot_by_ticker.get(str(p.get("ticker", "")).upper()))
        ]
        if len(kept_plays) < 2:
            candidates = []
            for d in matched:
                candidates.extend(d.get("strategy_candidates") or [])
            existing_types = {p.get("strategy_type") for p in kept_plays}
            for candidate in candidates:
                if len(kept_plays) >= 2:
                    break
                if candidate.get("strategy_type") not in existing_types:
                    kept_plays.append(candidate)
                    existing_types.add(candidate.get("strategy_type"))
        if kept_plays:
            raw["options_plays"] = kept_plays[:3]

        if hard_gate and not meets:
            _drop(
                raw,
                f"Failed multi-source bar: {independent} independent source(s), "
                f"{len(news_domains)} news domain(s); need "
                f"{settings.min_independent_sources}+ sources incl. 1 news domain",
            )
            continue

        validated.append(raw)

    return validated, dropped
