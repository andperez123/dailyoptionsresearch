from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

MACRO_SERIES = {
    "FEDFUNDS": "Fed Funds Rate",
    "DGS2": "2Y Treasury",
    "DGS10": "10Y Treasury",
    "T10Y2Y": "10Y-2Y Spread",
    "VIXCLS": "VIX",
    "UNRATE": "Unemployment",
    "CPIAUCSL": "CPI",
    "BAMLH0A0HYM2": "HY OAS",
}


async def _fetch_series(client: httpx.AsyncClient, series_id: str) -> dict[str, Any] | None:
    if not settings.fred_api_key:
        return None
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
    }
    try:
        response = await client.get(FRED_BASE, params=params)
        response.raise_for_status()
        payload = response.json()
        observations = payload.get("observations") or []
        if not observations:
            return None
        latest = observations[0]
        return {
            "series_id": series_id,
            "label": MACRO_SERIES.get(series_id, series_id),
            "date": latest.get("date"),
            "value": latest.get("value"),
        }
    except httpx.HTTPError as exc:
        logger.warning("FRED fetch failed for %s: %s", series_id, exc)
        return None


async def fetch_macro_snapshot(series_ids: list[str] | None = None) -> list[dict[str, Any]]:
    if not settings.fred_api_key:
        return []
    ids = series_ids or list(MACRO_SERIES.keys())
    async with httpx.AsyncClient(timeout=20.0) as client:
        results = await asyncio.gather(*[_fetch_series(client, series_id) for series_id in ids])
    return [item for item in results if item]
