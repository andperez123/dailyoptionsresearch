"""US-listed symbol universe (with company names) and on-disk caching.

Reddit ticker extraction is regex-based and noisy — any capitalized 2-5 letter
word is a candidate. This module provides the real symbol universe so
candidates can be validated before they enter the watchlist, plus a
ticker -> company-name map used to write better news queries and to match
headlines that mention the company without its symbol. Sources, in order:
Finnhub symbol directory (if keyed), then Nasdaq Trader symbol files (no key
required). Results are cached on disk and refreshed weekly; a stale cache is
preferred over no universe when every source fails.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import httpx

from config import settings

logger = logging.getLogger(__name__)

UNIVERSE_TTL_SECONDS = 7 * 24 * 3600
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

# Trailing corporate boilerplate stripped from security names so the remainder
# works as a news-search phrase ("Apple Inc. - Common Stock" -> "Apple").
_NAME_NOISE = re.compile(
    r"\s*[-–—]\s.*$"  # everything after " - " (share class / security type)
    r"|\s*\((.*?)\)\s*$",  # trailing parenthetical
)
_NAME_SUFFIXES = re.compile(
    r"[,\s]+(incorporated|inc\.?|corporation|corp\.?|company|co\.?|ltd\.?|plc|"
    r"holdings?|group|s\.?a\.?|n\.?v\.?|ag|se|lp|l\.p\.|llc|trust|"
    r"class [a-c])\s*$",
    re.IGNORECASE,
)


def clean_company_name(raw: str) -> str:
    """Reduce a listing security name to a searchable company name."""
    name = _NAME_NOISE.sub("", (raw or "").strip())
    for _ in range(3):
        stripped = _NAME_SUFFIXES.sub("", name).strip(" ,.")
        if stripped == name:
            break
        name = stripped
    return name.strip()


def _cache_path() -> Path:
    return Path(settings.database_path).parent / "ticker_universe.json"


def _read_cache() -> tuple[dict[str, str] | None, bool]:
    """Return (symbol->name map, is_fresh). (None, False) when unusable.

    Older caches stored only a symbol list; those are treated as usable but
    stale so names get backfilled on the next successful refresh."""
    try:
        payload = json.loads(_cache_path().read_text())
        symbols = list(payload["symbols"])
        if not symbols:
            return None, False
        names = payload.get("names") or {}
        directory = {s: names.get(s, "") for s in symbols}
        fresh = (time.time() - float(payload["fetched_at"])) <= UNIVERSE_TTL_SECONDS
        if not names:
            fresh = False
        return directory, fresh
    except Exception:
        return None, False


def _write_cache(directory: dict[str, str]) -> None:
    try:
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        _cache_path().write_text(
            json.dumps(
                {
                    "fetched_at": time.time(),
                    "symbols": sorted(directory),
                    "names": {s: n for s, n in directory.items() if n},
                }
            )
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


async def _fetch_finnhub_directory(client: httpx.AsyncClient) -> dict[str, str]:
    if not settings.finnhub_api_key:
        return {}
    response = await client.get(
        "https://finnhub.io/api/v1/stock/symbol",
        params={"exchange": "US", "token": settings.finnhub_api_key},
        timeout=30.0,
    )
    response.raise_for_status()
    directory: dict[str, str] = {}
    for row in response.json():
        cleaned = _clean_symbol(row.get("symbol", ""))
        if cleaned:
            description = (row.get("description") or "").title()
            directory[cleaned] = clean_company_name(description)
    return directory


def _parse_nasdaq_file(text: str, symbol_column: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines:
        return {}
    header = [col.strip() for col in lines[0].split("|")]
    try:
        idx = header.index(symbol_column)
    except ValueError:
        return {}
    try:
        name_idx = header.index("Security Name")
    except ValueError:
        name_idx = None
    directory: dict[str, str] = {}
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            break
        parts = line.split("|")
        if len(parts) <= idx:
            continue
        cleaned = _clean_symbol(parts[idx])
        if not cleaned:
            continue
        name = ""
        if name_idx is not None and len(parts) > name_idx:
            name = clean_company_name(parts[name_idx])
        directory[cleaned] = name
    return directory


async def _fetch_nasdaq_trader_directory(client: httpx.AsyncClient) -> dict[str, str]:
    directory: dict[str, str] = {}
    for url, column in ((NASDAQ_LISTED_URL, "Symbol"), (OTHER_LISTED_URL, "ACT Symbol")):
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
        directory.update(_parse_nasdaq_file(response.text, column))
    return directory


async def _load_directory() -> dict[str, str] | None:
    cached, fresh = _read_cache()
    if cached and fresh:
        return cached

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for fetcher in (_fetch_finnhub_directory, _fetch_nasdaq_trader_directory):
            try:
                directory = await fetcher(client)
            except Exception as exc:
                logger.warning("Ticker universe fetch failed via %s: %s", fetcher.__name__, exc)
                continue
            if len(directory) > 1000:
                _write_cache(directory)
                logger.info("Ticker universe refreshed: %s symbols", len(directory))
                return directory

    if cached:
        logger.warning("Using stale ticker universe cache (%s symbols)", len(cached))
        return cached
    logger.warning("No ticker universe available — skipping symbol validation")
    return None


async def get_ticker_universe() -> set[str] | None:
    """Return the set of valid US symbols, or None when unavailable.

    Callers must treat None as 'no filtering possible' rather than an empty
    universe, so a data-source outage never blanks the watchlist.
    """
    directory = await _load_directory()
    return set(directory) if directory is not None else None


async def get_ticker_names() -> dict[str, str]:
    """Ticker -> cleaned company name (empty dict when unavailable)."""
    directory = await _load_directory()
    if not directory:
        return {}
    return {sym: name for sym, name in directory.items() if name}
