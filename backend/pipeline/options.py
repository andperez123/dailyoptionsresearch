from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import yfinance as yf

from pipeline.strategies import classify_iv_regime


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
    next_expiry: str | None = None
    notable_calls: list[OptionContract] = field(default_factory=list)
    notable_puts: list[OptionContract] = field(default_factory=list)
    avg_iv: float | None = None
    atm_iv: float | None = None
    call_put_iv_skew: float | None = None
    iv_regime: str | None = None
    total_call_volume: int = 0
    total_put_volume: int = 0
    put_call_volume_ratio: float | None = None
    expiries_considered: list[str] = field(default_factory=list)
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


def _atm_iv_from_chain(calls, puts, price: float | None) -> tuple[float | None, float | None]:
    if price is None or price <= 0:
        return None, None
    call_iv = None
    put_iv = None
    if not calls.empty:
        calls = calls.copy()
        calls["dist"] = (calls["strike"] - price).abs()
        row = calls.sort_values("dist").iloc[0]
        call_iv = _safe_float(row.get("impliedVolatility"))
    if not puts.empty:
        puts = puts.copy()
        puts["dist"] = (puts["strike"] - price).abs()
        row = puts.sort_values("dist").iloc[0]
        put_iv = _safe_float(row.get("impliedVolatility"))
    atm = None
    vals = [v for v in (call_iv, put_iv) if v is not None]
    if vals:
        atm = round(sum(vals) / len(vals), 4)
    skew = None
    if call_iv is not None and put_iv is not None:
        skew = round(put_iv - call_iv, 4)
    return atm, skew


def fetch_options_snapshot(ticker: str) -> OptionsSnapshot:
    snapshot = OptionsSnapshot(ticker=ticker, current_price=None, nearest_expiry=None)
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        snapshot.current_price = _safe_float(info.get("regularMarketPrice") or info.get("currentPrice"))

        expiries = list(stock.options or [])
        if not expiries:
            snapshot.error = "No options chain available"
            return snapshot

        nearest = expiries[0]
        next_exp = expiries[1] if len(expiries) > 1 else None
        snapshot.nearest_expiry = nearest
        snapshot.next_expiry = next_exp
        snapshot.expiries_considered = expiries[:3]

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

        snapshot.atm_iv, snapshot.call_put_iv_skew = _atm_iv_from_chain(
            calls, puts, snapshot.current_price
        )
        snapshot.iv_regime = classify_iv_regime(snapshot.avg_iv, snapshot.put_call_volume_ratio)

        def top_contracts(df, option_type: str, expiry: str) -> list[OptionContract]:
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
                        expiry=expiry,
                        option_type=option_type,
                        volume=int(row.get("volume") or 0),
                        open_interest=int(row.get("openInterest") or 0),
                        implied_volatility=_safe_float(row.get("impliedVolatility")),
                        last_price=_safe_float(row.get("lastPrice")),
                        in_the_money=bool(row.get("inTheMoney", False)),
                    )
                )
            return contracts

        snapshot.notable_calls = top_contracts(calls, "call", nearest)
        snapshot.notable_puts = top_contracts(puts, "put", nearest)
    except Exception as exc:  # noqa: BLE001
        snapshot.error = str(exc)
    return snapshot


async def collect_options(tickers: list[str]) -> list[OptionsSnapshot]:
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, fetch_options_snapshot, ticker) for ticker in tickers]
    return await asyncio.gather(*tasks)
