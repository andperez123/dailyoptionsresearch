from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote_plus

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


def _is_fresh(published: str) -> bool:
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
    return age <= timedelta(hours=settings.news_max_age_hours)


async def fetch_feed(url: str, ticker: str | None = None, source_tier: str = "rss") -> list[NewsItem]:
    headers = {"User-Agent": settings.sec_user_agent}
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        parsed = feedparser.parse(response.text)
        items: list[NewsItem] = []
        for entry in parsed.entries[:12]:
            published = entry.get("published", "")
            if not _is_fresh(published):
                continue
            items.append(
                NewsItem(
                    title=entry.get("title", ""),
                    url=entry.get("link", ""),
                    source=entry.get("source", {}).get("title", parsed.feed.get("title", "News")),
                    published=published,
                    ticker=ticker,
                    source_tier=source_tier,
                )
            )
        return items


def match_tickers_in_text(text: str, watchlist: list[str]) -> list[str]:
    haystack = text.lower()
    matched: list[str] = []
    for ticker in watchlist:
        if re.search(rf"\$?{re.escape(ticker.lower())}\b", haystack):
            matched.append(ticker)
            continue
        for alias in COMPANY_ALIASES.get(ticker, []):
            if alias in haystack:
                matched.append(ticker)
                break
    return matched


async def collect_news(tickers: list[str]) -> list[NewsItem]:
    tasks = [fetch_feed(url) for url in MARKET_FEEDS]
    for ticker in tickers[:10]:
        query = quote_plus(f"{ticker} stock options")
        url = (
            "https://news.google.com/rss/search?q="
            f"{query}&hl=en-US&gl=US&ceid=US:en"
        )
        tasks.append(fetch_feed(url, ticker=ticker))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    seen_urls: set[str] = set()
    items: list[NewsItem] = []
    for result in results:
        if isinstance(result, Exception):
            continue
        for item in result:
            if item.url and item.url not in seen_urls:
                seen_urls.add(item.url)
                items.append(item)
    return items


async def collect_finance_news_for_watchlist(watchlist: list[str]) -> list[NewsItem]:
    from pipeline.finnhub import finnhub_client

    items = await collect_news(watchlist)
    if finnhub_client.enabled and watchlist:
        company_tasks = [finnhub_client.fetch_company_news(ticker) for ticker in watchlist[:8]]
        company_results = await asyncio.gather(*company_tasks, return_exceptions=True)
        seen = {item.url for item in items if item.url}
        for ticker, result in zip(watchlist[:8], company_results):
            if isinstance(result, Exception):
                continue
            for headline in result:
                if headline.url in seen:
                    continue
                seen.add(headline.url)
                items.append(
                    NewsItem(
                        title=headline.headline,
                        url=headline.url,
                        source="Finnhub",
                        published=headline.published_at.isoformat(),
                        ticker=ticker,
                        source_tier="finnhub",
                    )
                )
    return items
