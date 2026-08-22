from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote_plus, urlparse

import feedparser
import httpx

from config import settings
from time_utils import parse_rss_datetime, utc_now

MARKET_FEEDS = [
    "https://news.google.com/rss/search?q=stock+market+options&hl=en-US&gl=US&ceid=US:en",
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "https://finance.yahoo.com/news/rssindex",
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=&company=&dateb=&owner=include&count=40&output=atom",
]

# Static fallback aliases for when the universe directory has no name.
COMPANY_ALIASES: dict[str, list[str]] = {
    "AAPL": ["apple"],
    "MSFT": ["microsoft"],
    "GOOGL": ["google", "alphabet"],
    "AMZN": ["amazon"],
    "META": ["meta", "facebook"],
    "NVDA": ["nvidia"],
    "TSLA": ["tesla"],
}


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published: str = ""
    ticker: str | None = None
    source_tier: str = "rss"
    summary: str = ""
    # Domain of the actual publisher. Google News links all point at
    # news.google.com, which used to collapse every publisher into one
    # "independent domain" and silently break multi-source corroboration.
    publisher_domain: str = ""


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


_AGGREGATOR_DOMAINS = {"news.google.com", "google.com"}


def _is_fresh(published: str, max_age_hours: int | None = None) -> bool:
    if not published:
        return True
    try:
        published_at = parse_rss_datetime(published)
    except (TypeError, ValueError):
        return True
    now = utc_now()
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=now.tzinfo)
    age = now - published_at
    return age <= timedelta(hours=max_age_hours or settings.news_max_age_hours)


async def fetch_feed(
    url: str,
    ticker: str | None = None,
    source_tier: str = "rss",
    max_age_hours: int | None = None,
) -> list[NewsItem]:
    headers = {"User-Agent": settings.sec_user_agent}
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        parsed = feedparser.parse(response.text)
        items: list[NewsItem] = []
        for entry in parsed.entries[:15]:
            published = entry.get("published", "")
            if not _is_fresh(published, max_age_hours):
                continue
            title = entry.get("title", "") or ""
            summary = (
                entry.get("summary")
                or entry.get("description")
                or ""
            )
            if isinstance(summary, str):
                summary = re.sub(r"<[^>]+>", "", summary).strip()[:800]
            else:
                summary = ""
            if summary == title:
                summary = ""

            link = entry.get("link", "")
            # Google News entries carry the real publisher in <source>; the
            # link itself is an aggregator redirect.
            source_info = entry.get("source") or {}
            publisher_name = source_info.get("title", "") or ""
            publisher_domain = domain_of(source_info.get("href", "")) or domain_of(link)
            if publisher_domain in _AGGREGATOR_DOMAINS and publisher_name:
                # No source href — derive a stable pseudo-domain from the name
                # so distinct publishers still count as distinct sources.
                publisher_domain = re.sub(r"[^a-z0-9]", "", publisher_name.lower())
            source_name = publisher_name or parsed.feed.get("title", "News")
            # Google News appends " - Publisher" to titles; strip it since the
            # publisher is tracked separately.
            if publisher_name and title.endswith(f" - {publisher_name}"):
                title = title[: -len(f" - {publisher_name}")].rstrip()

            items.append(
                NewsItem(
                    title=title,
                    url=link,
                    source=source_name,
                    published=published,
                    ticker=ticker,
                    source_tier=source_tier,
                    summary=summary,
                    publisher_domain=publisher_domain,
                )
            )
        return items


def match_tickers_in_text(
    text: str,
    watchlist: list[str],
    names: dict[str, str] | None = None,
) -> list[str]:
    from pipeline.tickers import COMMON_WORDS

    haystack = text.lower()
    matched: list[str] = []
    for ticker in watchlist:
        # Tickers that are also common words only match as $CASHTAGS or via
        # their company name, never as the bare word.
        if ticker.upper() in COMMON_WORDS:
            symbol_pattern = rf"\${re.escape(ticker.lower())}\b"
        else:
            symbol_pattern = rf"\$?{re.escape(ticker.lower())}\b"
        if re.search(symbol_pattern, haystack):
            matched.append(ticker)
            continue
        aliases = list(COMPANY_ALIASES.get(ticker, []))
        if names and names.get(ticker):
            aliases.append(names[ticker].lower())
        if any(alias and alias in haystack for alias in aliases):
            matched.append(ticker)
    return matched


def _ticker_query(ticker: str, name: str | None) -> str:
    """News query for one ticker: the company name is a far better recall/
    precision tradeoff than '<TICK> stock options' when we know it."""
    if name and len(name) >= 3 and name.upper() != ticker.upper():
        return f'"{name}" OR "{ticker} stock"'
    return f"{ticker} stock"


async def collect_news(
    tickers: list[str],
    names: dict[str, str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    max_age_hours: int | None = None,
) -> list[NewsItem]:
    """Market-wide feeds + one Google News query per watchlist ticker.

    `date_from`/`date_to` scope queries to a historical window (used by the
    backfill); freshness filtering is disabled in that mode since 'fresh'
    is relative to the backfilled date, not now."""
    backfill = date_from is not None or date_to is not None
    effective_max_age = 24 * 365 if backfill else max_age_hours

    tasks = [fetch_feed(url, max_age_hours=effective_max_age) for url in MARKET_FEEDS]
    for ticker in tickers[:15]:
        query = _ticker_query(ticker, (names or {}).get(ticker))
        if date_from:
            query += f" after:{date_from.isoformat()}"
        if date_to:
            query += f" before:{date_to.isoformat()}"
        url = (
            "https://news.google.com/rss/search?q="
            f"{quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        )
        tasks.append(fetch_feed(url, ticker=ticker, max_age_hours=effective_max_age))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    items: list[NewsItem] = []
    for result in results:
        if isinstance(result, Exception):
            continue
        for item in result:
            title_key = re.sub(r"[^a-z0-9]", "", item.title.lower())[:80]
            if not item.url or item.url in seen_urls:
                continue
            if title_key and title_key in seen_titles:
                continue
            seen_urls.add(item.url)
            if title_key:
                seen_titles.add(title_key)
            items.append(item)
    return items


async def collect_finance_news_for_watchlist(
    watchlist: list[str],
    names: dict[str, str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[NewsItem]:
    from pipeline.finnhub import finnhub_client

    items = await collect_news(watchlist, names=names, date_from=date_from, date_to=date_to)
    if finnhub_client.enabled and watchlist:
        company_tasks = [finnhub_client.fetch_company_news(ticker) for ticker in watchlist[:10]]
        company_results = await asyncio.gather(*company_tasks, return_exceptions=True)
        seen = {item.url for item in items if item.url}
        for ticker, result in zip(watchlist[:10], company_results):
            if isinstance(result, Exception):
                continue
            for headline in result:
                if headline.url in seen:
                    continue
                seen.add(headline.url)
                summary = (headline.summary or "").strip()
                items.append(
                    NewsItem(
                        title=headline.headline,
                        url=headline.url,
                        source=headline.raw_payload.get("source", "Finnhub")
                        if isinstance(headline.raw_payload, dict)
                        else "Finnhub",
                        published=headline.published_at.isoformat(),
                        ticker=ticker,
                        source_tier="finnhub",
                        summary=summary if summary and summary != headline.headline else "",
                        publisher_domain=domain_of(headline.url),
                    )
                )
    # Prefer fresher items first for briefing consumers
    def sort_key(item: NewsItem) -> str:
        return item.published or ""

    items.sort(key=sort_key, reverse=True)
    return items
