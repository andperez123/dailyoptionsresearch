"""Deterministic market dashboard for the daily briefing.

Always-present, data-driven substance: even when no narrative clears the
multi-source bar, the report still shows index tape, watchlist movers, IV
extremes, unusual options prints, upcoming earnings, and buzz leaders.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import yfinance as yf

from pipeline.options import OptionsSnapshot

logger = logging.getLogger(__name__)

INDEX_SYMBOLS = ["SPY", "QQQ", "IWM", "^VIX"]


def _index_tape(as_of: date | None) -> list[dict[str, Any]]:
    end = (as_of or date.today()) + timedelta(days=1)
    start = end - timedelta(days=14)
    data = yf.download(
        INDEX_SYMBOLS,
        start=start.isoformat(),
        end=end.isoformat(),
        progress=False,
        auto_adjust=True,
        threads=True,
    )
    closes = (data["Close"] if "Close" in data else data).dropna(how="all")
    if as_of is not None:
        closes = closes[closes.index.date <= as_of]
    if len(closes) < 2:
        return []
    last, prev = closes.iloc[-1], closes.iloc[-2]
    tape: list[dict[str, Any]] = []
    for symbol in INDEX_SYMBOLS:
        try:
            p_last, p_prev = float(last[symbol]), float(prev[symbol])
        except (KeyError, TypeError, ValueError):
            continue
        if p_last != p_last or p_prev != p_prev or p_prev <= 0:  # NaN guards
            continue
        tape.append(
            {
                "symbol": symbol.lstrip("^"),
                "price": round(p_last, 2),
                "pct_change": round((p_last - p_prev) / p_prev * 100, 2),
            }
        )
    return tape


async def build_market_dashboard(
    *,
    options: list[OptionsSnapshot],
    earnings: list[tuple[str, str]] | None = None,
    buzz_deltas: dict[str, float] | None = None,
    ticker_counts: dict[str, int] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    try:
        indices = await asyncio.to_thread(_index_tape, as_of)
    except Exception as exc:
        logger.warning("Index tape fetch failed: %s", exc)
        indices = []

    movers = sorted(
        (
            {"ticker": o.ticker, "price": o.current_price, "pct_change": o.pct_change}
            for o in options
            if o.pct_change is not None
        ),
        key=lambda m: -abs(m["pct_change"] or 0),
    )[:6]

    iv_extremes: list[dict[str, Any]] = []
    for snap in options:
        rank = getattr(snap, "iv_rank", None)
        if rank is None:
            continue
        if rank >= 0.7 or rank <= 0.2:
            iv_extremes.append(
                {
                    "ticker": snap.ticker,
                    "iv_rank": round(rank, 2),
                    "atm_iv": getattr(snap, "atm_iv", None),
                    "regime": getattr(snap, "iv_regime", None),
                    "read": "rich premium — favor selling structures"
                    if rank >= 0.7
                    else "cheap premium — favor long options / debit structures",
                }
            )
    iv_extremes.sort(key=lambda x: -(x["iv_rank"] or 0))

    unusual_flow: list[dict[str, Any]] = []
    for snap in options:
        pcr = snap.put_call_volume_ratio
        if pcr is None:
            continue
        if pcr >= 1.5 or pcr <= 0.4:
            unusual_flow.append(
                {
                    "ticker": snap.ticker,
                    "put_call_ratio": pcr,
                    "read": "put-heavy flow" if pcr >= 1.5 else "call-heavy flow",
                }
            )

    buzz_leaders = [
        {"ticker": t, "buzz_z": z, "mentions": (ticker_counts or {}).get(t, 0)}
        for t, z in sorted((buzz_deltas or {}).items(), key=lambda kv: -kv[1])[:6]
        if z > 0
    ]

    return {
        "indices": indices,
        "watchlist_movers": movers,
        "iv_extremes": iv_extremes[:6],
        "unusual_flow": unusual_flow[:6],
        "earnings_ahead": [
            {"ticker": t, "date": d} for t, d in (earnings or [])[:8]
        ],
        "buzz_leaders": buzz_leaders,
    }
