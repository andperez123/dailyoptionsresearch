from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import yfinance as yf


@dataclass
class OptionContract:
    strike: float
    expiry: str
    option_type: str
    volume: int
    open_interest: int
    implied_volatility: float | None
    last_price: float | None
    in_the_money: bool


@dataclass
class OptionsSnapshot:
    ticker: str
    current_price: float | None
    nearest_expiry: str | None
    notable_calls: list[OptionContract] = field(default_factory=list)
    notable_puts: list[OptionContract] = field(default_factory=list)
    avg_iv: float | None = None
    total_call_volume: int = 0
    total_put_volume: int = 0
    put_call_volume_ratio: float | None = None
    error: str | None = None


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        val = float(value)
        if val != val:  # NaN
            return None
        return val
    except (TypeError, ValueError):
        return None


def fetch_options_snapshot(ticker: str) -> OptionsSnapshot:
    snapshot = OptionsSnapshot(ticker=ticker, current_price=None, nearest_expiry=None)
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        snapshot.current_price = _safe_float(info.get("regularMarketPrice") or info.get("currentPrice"))

        expiries = stock.options or []
        if not expiries:
            snapshot.error = "No options chain available"
            return snapshot

        nearest = expiries[0]
        snapshot.nearest_expiry = nearest
        chain = stock.option_chain(nearest)
        calls = chain.calls
        puts = chain.puts

        snapshot.total_call_volume = int(calls["volume"].fillna(0).sum())
        snapshot.total_put_volume = int(puts["volume"].fillna(0).sum())
        if snapshot.total_call_volume:
            snapshot.put_call_volume_ratio = round(
                snapshot.total_put_volume / snapshot.total_call_volume, 2
            )

        call_ivs = [_safe_float(v) for v in calls.get("impliedVolatility", [])]
        put_ivs = [_safe_float(v) for v in puts.get("impliedVolatility", [])]
        iv_values = [v for v in call_ivs + put_ivs if v is not None]
        if iv_values:
            snapshot.avg_iv = round(sum(iv_values) / len(iv_values), 4)

        def top_contracts(df, option_type: str) -> list[OptionContract]:
            if df.empty:
                return []
            df = df.copy()
            df["vol_oi"] = df["volume"].fillna(0) / df["openInterest"].replace(0, 1)
            df = df.sort_values(["volume", "vol_oi"], ascending=False).head(3)
            contracts: list[OptionContract] = []
            for _, row in df.iterrows():
                contracts.append(
                    OptionContract(
                        strike=float(row["strike"]),
                        expiry=nearest,
                        option_type=option_type,
                        volume=int(row.get("volume") or 0),
                        open_interest=int(row.get("openInterest") or 0),
                        implied_volatility=_safe_float(row.get("impliedVolatility")),
                        last_price=_safe_float(row.get("lastPrice")),
                        in_the_money=bool(row.get("inTheMoney", False)),
                    )
                )
            return contracts

        snapshot.notable_calls = top_contracts(calls, "call")
        snapshot.notable_puts = top_contracts(puts, "put")
    except Exception as exc:  # noqa: BLE001
        snapshot.error = str(exc)
    return snapshot


async def collect_options(tickers: list[str]) -> list[OptionsSnapshot]:
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, fetch_options_snapshot, ticker) for ticker in tickers]
    return await asyncio.gather(*tasks)
