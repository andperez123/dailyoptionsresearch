from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"


@dataclass
class NormalizedHeadline:
    provider: str
    external_id: str
    headline: str
    summary: str
    url: str
    published_at: datetime
    related_tickers: list[str]
    raw_payload: dict[str, Any]


@dataclass
class EarningsEvent:
    ticker: str
    date: str
    hour: str
    eps_estimate: Optional[float]
    revenue_estimate: Optional[float]


class FinnhubClient:
    def __init__(self) -> None:
        self.api_key = settings.finnhub_api_key
        self.enabled = bool(self.api_key)

    async def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        if not self.enabled:
            return None
        params = params or {}
        params["token"] = self.api_key
        async with httpx.AsyncClient(timeout=20.0) as client:
            for attempt in range(3):
                try:
                    response = await client.get(f"{FINNHUB_BASE}{path}", params=params)
                    if response.status_code == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPError as exc:
                    logger.warning("Finnhub request failed %s: %s", path, exc)
                    if attempt == 2:
                        return None
                    await asyncio.sleep(1)
        return None

    async def fetch_general_news(self, limit: int = 50) -> list[NormalizedHeadline]:
        data = await self._get("/news", {"category": "general", "minId": 0})
        if not data:
            return []
        headlines: list[NormalizedHeadline] = []
        for item in data[:limit]:
            headlines.append(
                NormalizedHeadline(
                    provider="finnhub",
                    external_id=str(item.get("id", item.get("datetime", ""))),
                    headline=item.get("headline", ""),
                    summary=item.get("summary", "")[:1000],
                    url=item.get("url", ""),
                    published_at=datetime.utcfromtimestamp(item.get("datetime", 0)),
                    related_tickers=[item.get("related", "")] if item.get("related") else [],
                    raw_payload=item,
                )
            )
        return headlines

    async def fetch_company_news(self, ticker: str, days_back: int = 3) -> list[NormalizedHeadline]:
        from datetime import date, timedelta

        end = date.today()
        start = end - timedelta(days=days_back)
        data = await self._get(
            "/company-news",
            {"symbol": ticker.upper(), "from": start.isoformat(), "to": end.isoformat()},
        )
        if not data:
            return []
        headlines: list[NormalizedHeadline] = []
        for item in data[:20]:
            headlines.append(
                NormalizedHeadline(
                    provider="finnhub",
                    external_id=str(item.get("id", f"{ticker}-{item.get('datetime')}")),
                    headline=item.get("headline", ""),
                    summary=item.get("summary", "")[:1000],
                    url=item.get("url", ""),
                    published_at=datetime.utcfromtimestamp(item.get("datetime", 0)),
                    related_tickers=[ticker.upper()],
                    raw_payload=item,
                )
            )
        return headlines

    async def fetch_earnings_calendar(self, from_date: str, to_date: str) -> list[EarningsEvent]:
        data = await self._get("/calendar/earnings", {"from": from_date, "to": to_date})
        if not data:
            return []
        events: list[EarningsEvent] = []
        for item in data.get("earningsCalendar", []):
            events.append(
                EarningsEvent(
                    ticker=item.get("symbol", ""),
                    date=item.get("date", ""),
                    hour=item.get("hour", ""),
                    eps_estimate=item.get("epsEstimate"),
                    revenue_estimate=item.get("revenueEstimate"),
                )
            )
        return events

    async def fetch_quote(self, ticker: str) -> Optional[dict[str, Any]]:
        return await self._get("/quote", {"symbol": ticker.upper()})

    async def fetch_company_profile(self, ticker: str) -> Optional[dict[str, Any]]:
        return await self._get("/stock/profile2", {"symbol": ticker.upper()})


finnhub_client = FinnhubClient()
