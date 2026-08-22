"""Daily close history with a raw Yahoo `spark` fallback.

yfinance's cookie/crumb session gets blocked from some server IPs while the
plain chart endpoints still respond to a browser user-agent. Movers screens
and the index tape only need (last, prev) closes, so when `yf.download`
returns nothing we fall back to the batched v7 spark endpoint directly.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx
import yfinance as yf

logger = logging.getLogger(__name__)

_SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_CHUNK = 20  # spark returns 400 above 20 symbols

Series = list[tuple[date, float]]


def _series_via_yf(symbols: list[str], start: date, end: date) -> dict[str, Series]:
    data = yf.download(
        symbols,
        start=start.isoformat(),
        end=end.isoformat(),
        progress=False,
        auto_adjust=True,
        threads=True,
    )
    if data is None or data.empty:
        return {}
    closes = data["Close"] if "Close" in data else data
    closes = closes.dropna(how="all")
    result: dict[str, Series] = {}
    for symbol in getattr(closes, "columns", []):
        series: Series = []
        for idx, value in closes[symbol].dropna().items():
            series.append((idx.date(), float(value)))
        if series:
            result[str(symbol)] = series
    return result


def _series_via_spark(symbols: list[str]) -> dict[str, Series]:
    result: dict[str, Series] = {}
    with httpx.Client(headers=_UA, timeout=20.0) as client:
        for i in range(0, len(symbols), _CHUNK):
            chunk = symbols[i : i + _CHUNK]
            try:
                response = client.get(
                    _SPARK_URL,
                    params={"symbols": ",".join(chunk), "range": "1mo", "interval": "1d"},
                )
                response.raise_for_status()
            except Exception as exc:
                logger.warning("Spark chunk failed (%s symbols): %s", len(chunk), exc)
                continue
            for entry in (response.json().get("spark") or {}).get("result") or []:
                symbol = entry.get("symbol", "")
                responses = entry.get("response") or []
                if not symbol or not responses:
                    continue
                payload = responses[0]
                timestamps = payload.get("timestamp") or []
                quotes = (payload.get("indicators") or {}).get("quote") or [{}]
                closes = quotes[0].get("close") or []
                series: Series = []
                for ts, close in zip(timestamps, closes):
                    if close is None:
                        continue
                    day = datetime.fromtimestamp(ts, tz=timezone.utc).date()
                    series.append((day, float(close)))
                if series:
                    result[symbol] = series
    return result


def fetch_daily_closes(symbols: list[str], start: date, end: date) -> dict[str, Series]:
    """Per-symbol (date, close) series, yfinance first, spark topping up
    whatever yfinance failed to return (partial blocks are common)."""
    try:
        series = _series_via_yf(symbols, start, end)
    except Exception as exc:
        logger.warning("yf.download failed: %s", exc)
        series = {}
    missing = [s for s in symbols if s not in series]
    if missing:
        logger.info("Yahoo spark fallback for %s symbols", len(missing))
        try:
            series.update(_series_via_spark(missing))
        except Exception as exc:
            logger.warning("Spark fallback failed: %s", exc)
    return series


def close_pair(series: Series, as_of: date | None) -> tuple[float, float] | None:
    """(last, previous) close at or before `as_of` (None = latest)."""
    points = [(d, c) for d, c in series if as_of is None or d <= as_of]
    if len(points) < 2:
        return None
    return points[-1][1], points[-2][1]
