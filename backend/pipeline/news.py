from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import quote_plus

import feedparser
import httpx

MARKET_FEEDS = [
    "https://news.google.com/rss/search?q=stock+market+options&hl=en-US&gl=US&ceid=US:en",
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "https://finance.yahoo.com/news/rssindex",
]


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published: str = ""
    ticker: str | None = None



async def fetch_feed(url: str, ticker: str | None = None) -> list[NewsItem]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        parsed = feedparser.parse(response.text)
        items: list[NewsItem] = []
        for entry in parsed.entries[:8]:
            items.append(
                NewsItem(
                    title=entry.get("title", ""),
                    url=entry.get("link", ""),
                    source=entry.get("source", {}).get("title", parsed.feed.get("title", "News")),
                    published=entry.get("published", ""),
                    ticker=ticker,
                )
            )
        return items


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
