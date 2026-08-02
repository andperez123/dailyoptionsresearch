from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import yfinance as yf

from config import settings
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
    iv_rank: float | None = None
    realized_vol_20d: float | None = None
    pct_change: float | None = None
    total_call_volume: int = 0
    total_put_volume: int = 0
    put_call_volume_ratio: float | None = None
    expiries_considered: list[str] = field(default_factory=list)
    # expiry -> strike -> {"call": quote, "put": quote}; quotes hold
    # bid/ask/mid/oi/volume/iv. Used for strike snapping, leg pricing, and
    # LLM play validation — intentionally not serialized into packets.
    chains: dict[str, dict[float, dict[str, Any]]] = field(default_factory=dict)
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


def _parse_expiry(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def select_target_expiries(
    expiries: list[str],
    today: date | None = None,
    min_front_dte: int | None = None,
    min_back_dte: int | None = None,
) -> tuple[str | None, str | None]:
    """Pick (front, back) expiries by target DTE instead of expiries[0].

    Front skips 0-2 DTE theta traps (first expiry with DTE >= min_front_dte,
    falling back to the last listed if none qualify). Back is the first expiry
    with DTE >= min_back_dte for calendars/diagonals (~30-45 DTE typical)."""
    today = today or date.today()
    front_min = min_front_dte if min_front_dte is not None else settings.options_min_front_dte
    back_min = min_back_dte if min_back_dte is not None else settings.options_min_back_dte

    dated = [(e, (parsed - today).days) for e in expiries if (parsed := _parse_expiry(e))]
    dated = [(e, dte) for e, dte in dated if dte >= 0]
    if not dated:
        return None, None

    front = next(((e, dte) for e, dte in dated if dte >= front_min), dated[-1])
    back = next(
        ((e, dte) for e, dte in dated if dte >= back_min and e != front[0]),
        None,
    )
    return front[0], back[0] if back else None


def _chain_quotes(df, price: float | None) -> dict[float, dict[str, Any]]:
    """Strike -> quote map, restricted to ±30% of spot to bound size."""
    quotes: dict[float, dict[str, Any]] = {}
    if df is None or df.empty:
        return quotes
    for _, row in df.iterrows():
        strike = _safe_float(row.get("strike"))
        if strike is None:
            continue
        if price and not (0.7 * price <= strike <= 1.3 * price):
            continue
        bid = _safe_float(row.get("bid")) or 0.0
        ask = _safe_float(row.get("ask")) or 0.0
        last = _safe_float(row.get("lastPrice")) or 0.0
        mid = round((bid + ask) / 2, 4) if bid > 0 and ask > 0 else last
        quotes[strike] = {
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "oi": int(row.get("openInterest") or 0),
            "volume": int(row.get("volume") or 0),
            "iv": _safe_float(row.get("impliedVolatility")),
        }
    return quotes


def _merge_chain(
    chains: dict[str, dict[float, dict[str, Any]]],
    expiry: str,
    calls: dict[float, dict[str, Any]],
    puts: dict[float, dict[str, Any]],
) -> None:
    merged: dict[float, dict[str, Any]] = {}
    for strike, quote in calls.items():
        merged.setdefault(strike, {})["call"] = quote
    for strike, quote in puts.items():
        merged.setdefault(strike, {})["put"] = quote
    chains[expiry] = merged


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


def _realized_vol_20d(stock: yf.Ticker) -> float | None:
    """Annualized 20-day close-to-close volatility — the implied-vs-realized
    comparison is the IV regime fallback until IV rank history accrues."""
    try:
        hist = stock.history(period="3mo")
        closes = hist["Close"].dropna()
        if len(closes) < 21:
            return None
        returns = closes.pct_change().dropna().tail(20)
        if returns.empty:
            return None
        return round(float(returns.std() * math.sqrt(252)), 4)
    except Exception:
        return None


def fetch_options_snapshot(ticker: str) -> OptionsSnapshot:
    snapshot = OptionsSnapshot(ticker=ticker, current_price=None, nearest_expiry=None)
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        snapshot.current_price = _safe_float(info.get("regularMarketPrice") or info.get("currentPrice"))
        prev_close = _safe_float(info.get("regularMarketPreviousClose") or info.get("previousClose"))
        if snapshot.current_price and prev_close:
            snapshot.pct_change = round(
                (snapshot.current_price - prev_close) / prev_close * 100, 2
            )

        expiries = list(stock.options or [])
        if not expiries:
            snapshot.error = "No options chain available"
            return snapshot

        front, back = select_target_expiries(expiries)
        if front is None:
            snapshot.error = "No usable expiries"
            return snapshot
        snapshot.nearest_expiry = front
        snapshot.next_expiry = back
        snapshot.expiries_considered = [e for e in (front, back) if e]

        chain = stock.option_chain(front)
        calls = chain.calls
        puts = chain.puts
        _merge_chain(
            snapshot.chains,
            front,
            _chain_quotes(calls, snapshot.current_price),
            _chain_quotes(puts, snapshot.current_price),
        )
        if back:
            try:
                back_chain = stock.option_chain(back)
                _merge_chain(
                    snapshot.chains,
                    back,
                    _chain_quotes(back_chain.calls, snapshot.current_price),
                    _chain_quotes(back_chain.puts, snapshot.current_price),
                )
            except Exception:
                snapshot.next_expiry = None

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
        snapshot.realized_vol_20d = _realized_vol_20d(stock)
        # Regime from ATM IV (chain-average IV is inflated by OTM smile wings).
        # iv_rank is attached later in the pipeline once history is loaded.
        snapshot.iv_regime = classify_iv_regime(
            snapshot.atm_iv if snapshot.atm_iv is not None else snapshot.avg_iv,
            realized_vol=snapshot.realized_vol_20d,
        )

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

        snapshot.notable_calls = top_contracts(calls, "call", front)
        snapshot.notable_puts = top_contracts(puts, "put", front)
    except Exception as exc:  # noqa: BLE001
        snapshot.error = str(exc)
    return snapshot


async def collect_options(tickers: list[str]) -> list[OptionsSnapshot]:
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, fetch_options_snapshot, ticker) for ticker in tickers]
    return await asyncio.gather(*tasks)
