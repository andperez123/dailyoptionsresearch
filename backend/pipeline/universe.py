"""US-listed symbol universe with on-disk caching.

Reddit ticker extraction is regex-based and noisy — any capitalized 2-5 letter
word is a candidate. This module provides the real symbol universe so
candidates can be validated before they enter the watchlist. Sources, in
order: Finnhub symbol directory (if keyed), then Nasdaq Trader symbol files
(no key required). Results are cached on disk and refreshed weekly; a stale
cache is preferred over no universe when every source fails.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from config import settings

logger = logging.getLogger(__name__)

UNIVERSE_TTL_SECONDS = 7 * 24 * 3600
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"


def _cache_path() -> Path:
    return Path(settings.database_path).parent / "ticker_universe.json"


def _read_cache() -> tuple[set[str] | None, bool]:
    """Return (symbols, is_fresh). (None, False) when no usable cache exists."""
    try:
        payload = json.loads(_cache_path().read_text())
        symbols = set(payload["symbols"])
        if not symbols:
            return None, False
        fresh = (time.time() - float(payload["fetched_at"])) <= UNIVERSE_TTL_SECONDS
        return symbols, fresh
    except Exception:
        return None, False


def _write_cache(symbols: set[str]) -> None:
    try:
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        _cache_path().write_text(
            json.dumps({"fetched_at": time.time(), "symbols": sorted(symbols)})
        )
    except Exception as exc:
        logger.warning("Failed to write ticker universe cache: %s", exc)


def _clean_symbol(raw: str) -> str | None:
    """Keep plain 1-5 letter symbols; unit/warrant/class suffixes won't match
    the Reddit extraction regex anyway."""
    symbol = (raw or "").strip().upper()
    if 1 <= len(symbol) <= 5 and symbol.isalpha():
        return symbol
    return None


async def _fetch_finnhub_symbols(client: httpx.AsyncClient) -> set[str]:
    if not settings.finnhub_api_key:
        return set()
    response = await client.get(
        "https://finnhub.io/api/v1/stock/symbol",
        params={"exchange": "US", "token": settings.finnhub_api_key},
        timeout=30.0,
    )
    response.raise_for_status()
    symbols: set[str] = set()
    for row in response.json():
        cleaned = _clean_symbol(row.get("symbol", ""))
        if cleaned:
            symbols.add(cleaned)
    return symbols


def _parse_nasdaq_file(text: str, symbol_column: str) -> set[str]:
    lines = text.splitlines()
    if not lines:
        return set()
    header = [col.strip() for col in lines[0].split("|")]
    try:
        idx = header.index(symbol_column)
    except ValueError:
        return set()
    symbols: set[str] = set()
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            break
        parts = line.split("|")
        if len(parts) <= idx:
            continue
        cleaned = _clean_symbol(parts[idx])
        if cleaned:
            symbols.add(cleaned)
    return symbols


async def _fetch_nasdaq_trader_symbols(client: httpx.AsyncClient) -> set[str]:
    symbols: set[str] = set()
    for url, column in ((NASDAQ_LISTED_URL, "Symbol"), (OTHER_LISTED_URL, "ACT Symbol")):
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
        symbols |= _parse_nasdaq_file(response.text, column)
    return symbols


async def get_ticker_universe() -> set[str] | None:
    """Return the set of valid US symbols, or None when unavailable.

    Callers must treat None as 'no filtering possible' rather than an empty
    universe, so a data-source outage never blanks the watchlist.
    """
    cached, fresh = _read_cache()
    if cached and fresh:
        return cached

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for fetcher in (_fetch_finnhub_symbols, _fetch_nasdaq_trader_symbols):
            try:
                symbols = await fetcher(client)
            except Exception as exc:
                logger.warning("Ticker universe fetch failed via %s: %s", fetcher.__name__, exc)
                continue
            if len(symbols) > 1000:
                _write_cache(symbols)
                logger.info("Ticker universe refreshed: %s symbols", len(symbols))
                return symbols

    if cached:
        logger.warning("Using stale ticker universe cache (%s symbols)", len(cached))
        return cached
    logger.warning("No ticker universe available — skipping symbol validation")
    return None
