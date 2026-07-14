from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

import yfinance as yf

from config import settings
from models import MarketSnapshot
from time_utils import market_status_now, utc_now

logger = logging.getLogger(__name__)


class MarketDataProvider(ABC):
    @abstractmethod
    def fetch_snapshot(self, symbol: str) -> MarketSnapshot:
        raise NotImplementedError


class YFinanceProvider(MarketDataProvider):
    def fetch_snapshot(self, symbol: str) -> MarketSnapshot:
        snapshot = MarketSnapshot(
            symbol=symbol,
            snapshot_at=utc_now(),
            provider="yfinance",
        )
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            hist = ticker.history(period="5d")
            price = info.get("regularMarketPrice") or info.get("currentPrice")
            prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
            volume = info.get("regularMarketVolume") or info.get("volume")
            pct_change = None
            if price and prev_close:
                pct_change = round(((price - prev_close) / prev_close) * 100, 2)

            relative_volume = None
            if not hist.empty and volume:
                avg_vol = hist["Volume"].mean()
                if avg_vol and avg_vol > 0:
                    relative_volume = round(volume / avg_vol, 2)

            iv = None
            try:
                expiries = ticker.options
                if expiries:
                    chain = ticker.option_chain(expiries[0])
                    ivs = chain.calls.get("impliedVolatility", []).dropna().tolist()
                    if ivs:
                        iv = round(sum(ivs) / len(ivs), 4)
            except Exception:
                pass

            snapshot.price = float(price) if price else None
            snapshot.pct_change = pct_change
            snapshot.volume = int(volume) if volume else None
            snapshot.relative_volume = relative_volume
            snapshot.implied_volatility = iv
        except Exception as exc:
            logger.warning("Market snapshot failed for %s: %s", symbol, exc)
        return snapshot


_provider = YFinanceProvider()


def get_market_provider() -> MarketDataProvider:
    return _provider


def fetch_snapshot(symbol: str) -> MarketSnapshot:
    return _provider.fetch_snapshot(symbol)


async def collect_pulse_snapshots() -> list[MarketSnapshot]:
    symbols = settings.pulse_symbols + settings.sector_etfs
    tasks = [asyncio.to_thread(fetch_snapshot, sym) for sym in symbols]
    return await asyncio.gather(*tasks)


async def collect_ticker_snapshot(ticker: str) -> MarketSnapshot:
    return await asyncio.to_thread(fetch_snapshot, ticker.upper())


__all__ = ["collect_pulse_snapshots", "collect_ticker_snapshot", "fetch_snapshot", "market_status_now"]
