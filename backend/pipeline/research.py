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
from pipeline.tickers import COMMON_WORDS
from time_utils import parse_rss_datetime, utc_now


def _ticker_in_text(ticker: str, text_upper: str, name: str = "") -> bool:
    """Symbol match that won't fire on plain English: tickers that are also
    common words (BY, ON, ALL...) only match as $CASHTAGS or via their
    company name — `\\bBY\\b` would otherwise match every headline containing
    the word 'by'."""
    if ticker in COMMON_WORDS:
        if re.search(rf"\${ticker}\b", text_upper):
            return True
        return bool(name) and len(name) >= 3 and name.upper() in text_upper
    return bool(re.search(rf"\${ticker}\b|\b{ticker}\b", text_upper))

# Conviction tiers replace the old hard multi-source gate. Narratives are
# never silently deleted for thin sourcing — they are labeled so the reader
# can calibrate, and only dossier-less (unsupported) theses get dropped.
TIER_CONFIRMED = "confirmed"    # multi-source bar met
TIER_DEVELOPING = "developing"  # at least one real news domain, not yet corroborated
TIER_WATCH = "watch"            # chatter/technicals only


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _news_domain(item: NewsItem) -> str:
    """Real publisher domain — Google News URLs all resolve to
    news.google.com, which must not count as a distinct source."""
    return getattr(item, "publisher_domain", "") or _domain(item.url)


def _parse_published(value: str | datetime | None) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=utc_now().tzinfo)
    try:
        return parse_rss_datetime(value)
    except Exception:
        return None


def _is_fresh(
    published: str | datetime | None,
    max_age_hours: int,
    now: datetime | None = None,
) -> bool:
    dt = _parse_published(published)
    if dt is None:
        return True
    reference = now or utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=reference.tzinfo)
    return (reference - dt) <= timedelta(hours=max_age_hours)


_CLAIM_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
    "after", "as", "is", "are", "was", "be", "at", "by", "its", "it",
    "from", "this", "that", "has", "have", "will", "says", "say", "said",
    "stock", "stocks", "shares", "share", "price", "market", "markets",
    "today", "new", "report", "reports", "reported", "amid", "over", "into",
    "why", "how", "what", "could", "may", "might", "up", "down", "more",
}


def _claim_tokens(text: str) -> set[str]:
    words = re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).split()
    return {w for w in words if w not in _CLAIM_STOPWORDS and len(w) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Two different headlines about the same event share most substantive tokens
# but rarely all of them — exact keyword-set matching (the old approach)
# almost never fired, so corroboration was structurally broken.
_CLAIM_SIMILARITY_THRESHOLD = 0.35


def cluster_claims(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Greedy single-pass clustering of claim entries by token overlap.

    Each entry: {"title": str, "domain": str, "url": str, "weight": int}.
    Returns corroborated clusters (2+ distinct domains or 2+ weighted
    mentions), strongest first."""
    clusters: list[dict[str, Any]] = []
    for entry in entries:
        tokens = _claim_tokens(entry.get("title", ""))
        if not tokens:
            continue
        best = None
        best_score = 0.0
        for cluster in clusters:
            score = _jaccard(tokens, cluster["tokens"])
            if score > best_score:
                best_score = score
                best = cluster
        if best is not None and best_score >= _CLAIM_SIMILARITY_THRESHOLD:
            best["tokens"] |= tokens
            if entry.get("domain"):
                best["domains"].add(entry["domain"])
            if entry.get("url"):
                best["urls"].append(entry["url"])
            best["count"] += int(entry.get("weight") or 1)
        else:
            clusters.append(
                {
                    "claim": entry.get("title", ""),
                    "tokens": set(tokens),
                    "domains": {entry["domain"]} if entry.get("domain") else set(),
                    "urls": [entry["url"]] if entry.get("url") else [],
                    "count": int(entry.get("weight") or 1),
                }
            )

    corroborated = []
    for cluster in clusters:
        domain_count = len(cluster["domains"])
        if domain_count >= 2 or cluster["count"] >= 2:
            corroborated.append(
                {
                    "claim": cluster["claim"],
                    "independent_domains": sorted(cluster["domains"]),
                    "domain_count": domain_count,
                    "mention_count": cluster["count"],
                    "urls": cluster["urls"][:4],
                }
            )
    corroborated.sort(key=lambda c: (-c["domain_count"], -c["mention_count"]))
    return corroborated


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
    ticker_names: dict[str, str] | None = None,
    now: datetime | None = None,
    candidate_sources: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Build per-ticker multi-source research packets with corroboration metrics."""
    max_age = max_age_hours if max_age_hours is not None else settings.briefing_news_max_age_hours
    options_by_ticker = {o.ticker.upper(): o for o in options}
    names = ticker_names or {}
    dossiers: list[dict[str, Any]] = []

    ticker_set = {t.upper() for t in tickers}
    news_by_ticker: dict[str, list[NewsItem]] = defaultdict(list)
    for item in news:
        if not _is_fresh(item.published, max_age, now=now):
            continue
        related = []
        if item.ticker:
            related.append(item.ticker.upper())
        # Also attach when the symbol or the company name appears in the title
        title_upper = item.title.upper()
        title_lower = item.title.lower()
        for t in ticker_set:
            if _ticker_in_text(t, title_upper, names.get(t, "")):
                related.append(t)
                continue
            name = (names.get(t) or "").lower()
            if name and len(name) >= 3 and name in title_lower:
                related.append(t)
        for t in set(related):
            if t in ticker_set:
                news_by_ticker[t].append(item)

    posts_by_ticker: dict[str, list[RedditPost]] = defaultdict(list)
    for post in finance_posts:
        blob = f"{post.title} {post.selftext or ''}".upper()
        for t in tickers:
            if _ticker_in_text(t.upper(), blob, names.get(t.upper(), "")):
                posts_by_ticker[t.upper()].append(post)

    cats_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cat in overnight_catalysts:
        primary = (cat.get("primary_ticker") or "").upper()
        related = [str(x).upper() for x in cat.get("related_tickers") or []]
        for t in {primary, *related}:
            if t and t in ticker_set:
                cats_by_ticker[t].append(cat)

    for ticker in tickers:
        t = ticker.upper()
        sources: list[dict[str, Any]] = []
        claim_entries: list[dict[str, Any]] = []

        for item in news_by_ticker.get(t, [])[:12]:
            domain = _news_domain(item) or item.source or "news"
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
            claim_entries.append(
                {"title": item.title, "domain": domain, "url": item.url, "weight": 1}
            )

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
            cat_domain = _domain(cat.get("source_url") or "") or "catalyst"
            sources.append(
                {
                    "title": cat.get("headline") or cat.get("thesis") or "catalyst",
                    "url": cat.get("source_url") or "",
                    "source": cat.get("source_name") or "catalyst",
                    "domain": cat_domain,
                    "source_type": "catalyst",
                    "provider": cat.get("source_name") or "catalyst",
                    "published": cat.get("published_at") or cat.get("detected_at") or "",
                    "summary": cat.get("summary") or cat.get("thesis") or "",
                    "impact_score": cat.get("impact_score"),
                    "direction": cat.get("direction"),
                    "supporting_source_count": cat.get("supporting_source_count"),
                }
            )
            claim_entries.append(
                {
                    "title": cat.get("headline") or cat.get("thesis") or "",
                    "domain": cat_domain,
                    "url": cat.get("source_url") or "",
                    "weight": int(cat.get("supporting_source_count") or 1),
                }
            )

        # Independent = distinct real news domains, plus reddit/catalyst boosts
        domains = {s["domain"] for s in sources if s.get("domain")}
        source_types = {s["source_type"] for s in sources if s.get("source_type")}
        # Reddit alone should not count as multi-source confirmation
        independent_news_domains = {
            d for d in domains if d not in {"", "reddit.com", "catalyst"}
        }
        independent_source_count = len(independent_news_domains) + (
            1 if "reddit" in source_types else 0
        ) + (1 if "catalyst" in source_types and independent_news_domains else 0)

        corroborated_claims = cluster_claims(claim_entries)

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
        reference_now = now or utc_now()
        for s in sources:
            dt = _parse_published(s.get("published"))
            if dt:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=reference_now.tzinfo)
                freshness_hours.append(
                    round((reference_now - dt).total_seconds() / 3600, 1)
                )
        newest_hours = min(freshness_hours) if freshness_hours else None

        meets_bar = (
            independent_source_count >= settings.min_independent_sources
            and len(independent_news_domains) >= 1
        )
        if meets_bar:
            tier = TIER_CONFIRMED
        elif independent_news_domains or corroborated_claims:
            tier = TIER_DEVELOPING
        else:
            tier = TIER_WATCH

        research_quality = {
            "independent_source_count": independent_source_count,
            "distinct_domains": sorted(domains)[:12],
            "source_types": sorted(source_types),
            "news_domain_count": len(independent_news_domains),
            "corroborated_claim_count": len(corroborated_claims),
            "newest_source_age_hours": newest_hours,
            "meets_multi_source_bar": meets_bar,
            "conviction_tier": tier,
            "max_age_hours_applied": max_age,
        }

        dossiers.append(
            {
                "ticker": t,
                "mention_count": ticker_counts.get(t, ticker_counts.get(ticker, 0)),
                "buzz_delta": buzz_deltas.get(t, buzz_deltas.get(ticker, 0.0)),
                "candidate_sources": (candidate_sources or {}).get(t, []),
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
                "candidate_sources": d.get("candidate_sources", []),
                "source_count": len(d.get("sources") or []),
                "independent_source_count": independent,
                "news_domain_count": news_domains,
                "source_types": source_types,
                "corroborated_claim_count": quality.get("corroborated_claim_count", 0),
                "newest_source_age_hours": quality.get("newest_source_age_hours"),
                "strategy_candidates": len(d.get("strategy_candidates") or []),
                "meets_multi_source_bar": meets,
                "conviction_tier": quality.get("conviction_tier", TIER_WATCH),
                "fail_reason": reason,
            }
        )
    return verdicts


_TIER_ORDER = {TIER_CONFIRMED: 0, TIER_DEVELOPING: 1, TIER_WATCH: 2}


def validate_narratives(
    narratives: list[dict[str, Any]],
    dossiers: list[dict[str, Any]],
    *,
    require_multi_source: bool | None = None,
    options: list[OptionsSnapshot] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach research_quality with a conviction tier, sanity-check options
    plays against the real chain, and sort confirmed narratives first.

    Narratives are only dropped when they reference tickers with no research
    dossier at all (unsupported/hallucinated theses). Thin sourcing demotes
    the tier instead of deleting the content — an empty report is a worse
    failure mode than a labeled low-confidence one. Returns (kept, dropped)."""
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
                "conviction_tier": TIER_WATCH,
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
        if meets:
            tier = TIER_CONFIRMED
        elif news_domains or corroborated:
            tier = TIER_DEVELOPING
        else:
            tier = TIER_WATCH
        raw["research_quality"] = {
            "independent_source_count": independent,
            "news_domain_count": len(news_domains),
            "source_types": sorted(source_types),
            "corroborated_claim_count": corroborated,
            "meets_multi_source_bar": meets,
            "conviction_tier": tier,
            "dossier_tickers": [d["ticker"] for d in matched],
        }
        if tier != TIER_CONFIRMED:
            raw["research_quality"]["warning"] = (
                "Multi-source bar not met — treat as "
                f"{tier} conviction, not a confirmed story"
            )

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

        validated.append(raw)

    validated.sort(
        key=lambda n: _TIER_ORDER.get(
            (n.get("research_quality") or {}).get("conviction_tier", TIER_WATCH), 2
        )
    )
    return validated, dropped
