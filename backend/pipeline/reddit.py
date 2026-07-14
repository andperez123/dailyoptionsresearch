from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import logging
import time

import feedparser
import httpx

from config import settings

logger = logging.getLogger(__name__)

from pipeline.tickers import extract_ticker_set as extract_tickers


@dataclass
class RedditPost:
    subreddit: str
    title: str
    selftext: str
    url: str
    permalink: str
    score: int
    num_comments: int
    created_utc: float
    top_comments: list[str] = field(default_factory=list)


async def fetch_subreddit_posts_rss(
    client: httpx.AsyncClient,
    subreddit: str,
    sort: str = "hot",
    limit: int = 25,
) -> list[RedditPost]:
    url = f"https://www.reddit.com/r/{subreddit}/{sort}/.rss?limit={limit}"
    headers = {"User-Agent": settings.reddit_user_agent}
    response = await client.get(url, headers=headers, timeout=20.0)
    response.raise_for_status()
    parsed = feedparser.parse(response.text)
    posts: list[RedditPost] = []
    for entry in parsed.entries[:limit]:
        link = entry.get("link", "")
        posts.append(
            RedditPost(
                subreddit=subreddit,
                title=entry.get("title", ""),
                selftext=entry.get("summary", "")[:1500],
                url=link,
                permalink=link.replace("https://www.reddit.com", "").split("?")[0],
                score=0,
                num_comments=0,
                created_utc=time.time(),
            )
        )
    return posts


async def fetch_subreddit_posts(
    client: httpx.AsyncClient,
    subreddit: str,
    sort: str = "hot",
    limit: int = 25,
) -> list[RedditPost]:
    url = f"https://old.reddit.com/r/{subreddit}/{sort}.json?limit={limit}"
    headers = {
        "User-Agent": settings.reddit_user_agent,
        "Accept": "application/json",
    }
    try:
        response = await client.get(url, headers=headers, timeout=20.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Reddit JSON blocked for r/%s (%s), falling back to RSS", subreddit, exc)
        return await fetch_subreddit_posts_rss(client, subreddit, sort, limit)

    payload = response.json()
    posts: list[RedditPost] = []

    for child in payload.get("data", {}).get("children", []):
        data = child.get("data", {})
        permalink = data.get("permalink", "")
        post = RedditPost(
            subreddit=subreddit,
            title=data.get("title", ""),
            selftext=data.get("selftext", "")[:1500],
            url=f"https://old.reddit.com{permalink}",
            permalink=permalink,
            score=data.get("score", 0),
            num_comments=data.get("num_comments", 0),
            created_utc=data.get("created_utc", 0),
        )
        posts.append(post)

    return posts


async def fetch_post_comments(
    client: httpx.AsyncClient,
    permalink: str,
    limit: int = 5,
) -> list[str]:
    if not permalink:
        return []
    url = f"https://old.reddit.com{permalink}.json?limit={limit}&depth=1"
    headers = {
        "User-Agent": settings.reddit_user_agent,
        "Accept": "application/json",
    }
    try:
        response = await client.get(url, headers=headers, timeout=20.0)
        response.raise_for_status()
        payload = response.json()
        comments: list[str] = []
        if len(payload) > 1:
            for child in payload[1].get("data", {}).get("children", [])[:limit]:
                body = child.get("data", {}).get("body", "")
                if body and body not in ("[deleted]", "[removed]"):
                    comments.append(body[:500])
        return comments
    except httpx.HTTPError:
        return []


async def collect_reddit_posts(
    subreddits: list[str] | None = None,
    posts_per_sub: int = 20,
) -> list[RedditPost]:
    subs = subreddits or settings.reddit_subreddits
    async with httpx.AsyncClient(follow_redirects=True) as client:
        posts: list[RedditPost] = []
        for sub in subs:
            try:
                batch = await fetch_subreddit_posts(client, sub, limit=posts_per_sub)
                posts.extend(batch)
            except Exception as exc:
                logger.warning("Reddit fetch failed for r/%s: %s", sub, exc)
            await asyncio.sleep(1.5)

        # Fetch comments for top posts by engagement
        posts.sort(key=lambda p: p.score + p.num_comments, reverse=True)
        comment_tasks = [
            fetch_post_comments(client, post.permalink)
            for post in posts[:12]
        ]
        comment_results = await asyncio.gather(*comment_tasks, return_exceptions=True)
        for post, comments in zip(posts[:12], comment_results):
            if isinstance(comments, list):
                post.top_comments = comments

    return posts


def count_ticker_mentions(posts: list[RedditPost]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for post in posts:
        text = " ".join([post.title, post.selftext, *post.top_comments])
        for ticker in extract_tickers(text):
            counts[ticker] = counts.get(ticker, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))
