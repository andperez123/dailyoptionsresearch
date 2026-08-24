"""Deterministic multi-leg options strategy proposals from chain + catalyst context.

Strike selection prefers the real chain when available: targets are derived
from the expected move (price * IV * sqrt(DTE/365)) and snapped to listed,
liquid strikes. When no chain is supplied (tests, degraded data), synthetic
rounded strikes keep the engine functional.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional


STRATEGY_CATALOG = {
    "debit_call_spread": {
        "direction": "bullish",
        "edge": "Defined-risk upside — cheaper than naked calls when IV is elevated",
    },
    "debit_put_spread": {
        "direction": "bearish",
        "edge": "Defined-risk downside — caps premium bleed vs naked puts",
    },
    "credit_put_spread": {
        "direction": "bullish",
        "edge": "Collect premium with bullish/neutral bias; wins if price stays above short put",
    },
    "credit_call_spread": {
        "direction": "bearish",
        "edge": "Collect premium with bearish/neutral bias; wins if price stays below short call",
    },
    "long_strangle": {
        "direction": "volatility",
        "edge": "Profits from a large move either way — use when catalyst can expand realized vol",
    },
    "iron_condor": {
        "direction": "neutral",
        "edge": "Collect premium in a range — use when IV is rich and no binary catalyst",
    },
    "iron_butterfly": {
        "direction": "neutral",
        "edge": "Tighter range premium harvest around ATM when expecting pin/quiet tape",
    },
    "calendar_call": {
        "direction": "bullish",
        "edge": "Longer-dated long call vs short near-term — harvest front-month theta/IV crush",
    },
    "calendar_put": {
        "direction": "bearish",
        "edge": "Longer-dated long put vs short near-term — event IV crush + directional lean",
    },
    "diagonal_call": {
        "direction": "bullish",
        "edge": "Bullish diagonal — roll strike for leverage while selling near-term premium",
    },
    "jade_lizard": {
        "direction": "bullish",
        "edge": "Short put + short call credit spread — no upside risk if credit ≥ call width",
    },
    "risk_reversal": {
        "direction": "bullish",
        "edge": "Sell OTM put / buy OTM call — synthetic long with financing from put premium",
    },
}

# Catalyst half-life → whether directional long-premium legs should use the
# longer-dated expiry so the thesis has room to play out.
_LONG_HALF_LIVES = {"1-2_weeks", "longer_term"}

# Below this many days to expiry, short-premium range structures are theta
# traps for a daily research product rather than deliberate 0DTE plays.
MIN_DTE_FOR_PREMIUM_SELLING = 3


@dataclass
class StrategyProposal:
    ticker: str
    strategy_type: str
    direction: str
    structure: str
    strike_zone: str
    expiry: str
    legs: list[dict[str, Any]]
    edge: str
    thesis: str
    iv_note: str
    max_loss: str
    max_gain: str
    breakeven: str
    when_it_wins: str
    when_it_loses: str
    degen_score: int
    risk_note: str
    regime: str


def compute_iv_rank(history: list[float], current: Optional[float]) -> Optional[float]:
    """Position of current ATM IV within its trailing range. Needs enough
    observations to be meaningful; returns None otherwise."""
    if current is None or len(history) < 10:
        return None
    lo = min(*history, current)
    hi = max(*history, current)
    if hi - lo < 1e-6:
        return 0.5
    return round((current - lo) / (hi - lo), 3)


def classify_iv_regime(
    iv: Optional[float],
    *,
    iv_rank: Optional[float] = None,
    realized_vol: Optional[float] = None,
) -> str:
    """IV regime, best signal first: IV rank vs own history, then implied vs
    realized (variance premium), then absolute level as a last resort."""
    if iv_rank is not None:
        if iv_rank >= 0.65:
            return "elevated"
        if iv_rank >= 0.30:
            return "moderate"
        return "cheap"
    if iv is not None and realized_vol and realized_vol > 0:
        ratio = iv / realized_vol
        if ratio >= 1.25:
            return "elevated"
        if ratio >= 0.95:
            return "moderate"
        return "cheap"
    if iv is None:
        return "unknown"
    if iv >= 0.55:
        return "elevated"
    if iv >= 0.35:
        return "moderate"
    return "cheap"


def classify_bias(
    direction: str | None,
    put_call_ratio: Optional[float],
    pct_change: Optional[float],
) -> str:
    d = (direction or "").lower()
    if d in {"bullish", "bearish", "volatility", "neutral", "mixed"}:
        if d == "mixed":
            return "volatility"
        return d
    if put_call_ratio is not None and put_call_ratio >= 1.3:
        return "bearish"
    if put_call_ratio is not None and put_call_ratio <= 0.7:
        return "bullish"
    if pct_change is not None and abs(pct_change) >= 3:
        return "volatility"
    return "neutral"


def _dte(expiry: Optional[str], today: Optional[date] = None) -> Optional[int]:
    if not expiry:
        return None
    try:
        exp = datetime.strptime(expiry[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (exp - (today or date.today())).days


def _expected_move(price: float, iv: Optional[float], dte: Optional[int]) -> Optional[float]:
    if not iv or iv <= 0:
        return None
    days = max(dte or 7, 1)
    return price * iv * math.sqrt(days / 365.0)


def _round_strike(price: float) -> float:
    if price >= 200:
        step = 5.0
    elif price >= 50:
        step = 5.0
    elif price >= 20:
        step = 1.0
    else:
        step = 0.5
    return round(price / step) * step


def _fallback_strikes(price: float) -> dict[str, float]:
    atm = _round_strike(price)
    width = 5.0 if price >= 50 else (2.5 if price >= 20 else 1.0)
    if price >= 200:
        width = 10.0
    return {
        "atm": atm,
        "otm_call": atm + width,
        "further_otm_call": atm + 2 * width,
        "otm_put": atm - width,
        "further_otm_put": atm - 2 * width,
    }


class _ChainPicker:
    """Snaps target strikes to listed, liquid contracts and prices legs from mids.

    `chains` maps expiry -> strike -> {"call": quote, "put": quote} where a
    quote holds bid/ask/mid/oi/volume/iv. Spread-width checks only apply when
    a live two-sided market exists (pre-open yfinance often reports 0/0)."""

    def __init__(
        self,
        chains: dict[str, dict[float, dict[str, Any]]] | None,
        min_oi: int,
        max_spread_pct: Optional[float],
    ) -> None:
        self.chains = chains or {}
        self.min_oi = min_oi
        self.max_spread_pct = max_spread_pct

    def has_expiry(self, expiry: Optional[str]) -> bool:
        return bool(expiry) and expiry in self.chains

    def _quote(self, expiry: str, option_type: str, strike: float) -> dict[str, Any] | None:
        return (self.chains.get(expiry, {}).get(strike) or {}).get(option_type)

    def _is_liquid(self, quote: dict[str, Any] | None) -> bool:
        if not quote:
            return False
        if (quote.get("mid") or 0) <= 0:
            return False
        if (quote.get("oi") or 0) < self.min_oi:
            return False
        bid, ask = quote.get("bid") or 0, quote.get("ask") or 0
        if bid > 0 and ask > 0 and self.max_spread_pct is not None:
            mid = (bid + ask) / 2
            if mid > 0 and ((ask - bid) / mid) * 100 > self.max_spread_pct:
                return False
        return True

    def liquid_strikes(self, expiry: str, option_type: str) -> list[float]:
        return sorted(
            strike
            for strike, sides in self.chains.get(expiry, {}).items()
            if self._is_liquid(sides.get(option_type))
        )

    def snap(
        self,
        expiry: str,
        option_type: str,
        target: float,
        *,
        strictly_above: Optional[float] = None,
        strictly_below: Optional[float] = None,
    ) -> Optional[float]:
        candidates = self.liquid_strikes(expiry, option_type)
        if strictly_above is not None:
            candidates = [s for s in candidates if s > strictly_above]
        if strictly_below is not None:
            candidates = [s for s in candidates if s < strictly_below]
        if not candidates:
            return None
        return min(candidates, key=lambda s: abs(s - target))

    def mid(self, expiry: str, option_type: str, strike: float) -> Optional[float]:
        quote = self._quote(expiry, option_type, strike)
        if not quote:
            return None
        mid = quote.get("mid")
        return float(mid) if mid and mid > 0 else None

    def net_cost(self, legs: list[dict[str, Any]]) -> Optional[float]:
        """Net debit (positive) or credit (negative) per share from mids.
        None when any leg lacks a usable quote."""
        total = 0.0
        for leg in legs:
            mid = self.mid(leg["expiry"], leg["option_type"], float(leg["strike"]))
            if mid is None:
                return None
            sign = 1.0 if leg["action"] == "buy" else -1.0
            total += sign * mid * leg.get("quantity", 1)
        return round(total, 2)


def _fmt(value: Optional[float]) -> str:
    return f"${value:,.2f}" if value is not None else "n/a"


def _leg(action: str, option_type: str, strike: float, expiry: str) -> dict[str, Any]:
    return {
        "action": action,
        "option_type": option_type,
        "strike": f"{strike:g}",
        "expiry": expiry,
        "quantity": 1,
    }


def propose_strategies(
    ticker: str,
    price: Optional[float],
    nearest_expiry: Optional[str],
    next_expiry: Optional[str] = None,
    avg_iv: Optional[float] = None,
    put_call_ratio: Optional[float] = None,
    pct_change: Optional[float] = None,
    catalyst_direction: Optional[str] = None,
    catalyst_type: Optional[str] = None,
    half_life: Optional[str] = None,
    limit: int = 3,
    *,
    atm_iv: Optional[float] = None,
    iv_rank: Optional[float] = None,
    realized_vol: Optional[float] = None,
    iv_skew: Optional[float] = None,
    chains: dict[str, dict[float, dict[str, Any]]] | None = None,
    min_leg_open_interest: int = 0,
    max_leg_spread_pct: Optional[float] = None,
    today: Optional[date] = None,
) -> list[StrategyProposal]:
    if price is None or price <= 0 or not nearest_expiry:
        return []

    iv = atm_iv if atm_iv is not None else avg_iv
    regime = classify_iv_regime(iv, iv_rank=iv_rank, realized_vol=realized_vol)
    bias = classify_bias(catalyst_direction, put_call_ratio, pct_change)
    far_expiry = next_expiry or nearest_expiry
    front_dte = _dte(nearest_expiry, today)
    back_dte = _dte(far_expiry, today)
    picker = _ChainPicker(chains, min_leg_open_interest, max_leg_spread_pct)
    liquidity_note = ""

    # Directional long-premium legs go further out when the catalyst needs
    # time; short-premium stays front where theta decays fastest.
    directional_expiry = (
        far_expiry
        if (half_life or "").lower() in _LONG_HALF_LIVES and far_expiry != nearest_expiry
        else nearest_expiry
    )
    directional_dte = _dte(directional_expiry, today) or front_dte
    can_sell_premium = front_dte is None or front_dte >= MIN_DTE_FOR_PREMIUM_SELLING

    # --- Strike selection: expected-move targets snapped to the liquid chain ---
    em = _expected_move(price, iv, front_dte)

    def strikes_for(expiry: str) -> dict[str, float] | None:
        exp_dte = _dte(expiry, today) or front_dte
        exp_em = _expected_move(price, iv, exp_dte)
        fallback = _fallback_strikes(price)
        width = fallback["otm_call"] - fallback["atm"]
        call_target = price + (0.6 * exp_em if exp_em else width)
        call_wing_target = price + (1.2 * exp_em if exp_em else 2 * width)
        put_target = price - (0.6 * exp_em if exp_em else width)
        put_wing_target = price - (1.2 * exp_em if exp_em else 2 * width)

        if not picker.has_expiry(expiry):
            return {
                "atm_call": fallback["atm"],
                "atm_put": fallback["atm"],
                "otm_call": fallback["otm_call"],
                "further_otm_call": fallback["further_otm_call"],
                "otm_put": fallback["otm_put"],
                "further_otm_put": fallback["further_otm_put"],
            }

        atm_call = picker.snap(expiry, "call", price)
        atm_put = picker.snap(expiry, "put", price)
        if atm_call is None or atm_put is None:
            return None
        otm_call = picker.snap(expiry, "call", call_target, strictly_above=atm_call)
        further_call = (
            picker.snap(expiry, "call", call_wing_target, strictly_above=otm_call)
            if otm_call is not None
            else None
        )
        otm_put = picker.snap(expiry, "put", put_target, strictly_below=atm_put)
        further_put = (
            picker.snap(expiry, "put", put_wing_target, strictly_below=otm_put)
            if otm_put is not None
            else None
        )
        if otm_call is None or otm_put is None:
            return None
        # Wings stay None when no liquid listed strike exists — structures
        # that need them are skipped rather than quoting an unlisted strike.
        return {
            "atm_call": atm_call,
            "atm_put": atm_put,
            "otm_call": otm_call,
            "further_otm_call": further_call,
            "otm_put": otm_put,
            "further_otm_put": further_put,
        }

    front = strikes_for(nearest_expiry)
    if front is None:
        # Progressive relaxation instead of a blank engine: a thin chain (or
        # a pre-open one with one-sided quotes) should degrade to labeled
        # lower-liquidity proposals, not zero analysis.
        picker = _ChainPicker(chains, 0, None)
        front = strikes_for(nearest_expiry)
        if front is not None:
            liquidity_note = (
                "Liquidity below preferred thresholds "
                f"(OI<{min_leg_open_interest} or wide spreads) — use limit orders and size down"
            )
        else:
            picker = _ChainPicker(None, 0, None)
            front = strikes_for(nearest_expiry)
            liquidity_note = (
                "No live liquid quotes near the targets — strikes are synthetic targets; "
                "verify listed strikes and quotes before entry"
            )
    if front is None:
        return []
    directional = strikes_for(directional_expiry) or front

    iv_pct = f"{iv:.0%}" if iv is not None else "n/a"
    rank_note = f", IV rank {iv_rank:.0%}" if iv_rank is not None else ""
    skew_note = f", put-call skew {iv_skew:+.1%}" if iv_skew is not None else ""
    iv_context = f"IV regime={regime} ({iv_pct}{rank_note}{skew_note})"
    eventy = (catalyst_type or "").lower() in {
        "earnings",
        "guidance",
        "regulatory",
        "merger",
        "legal",
        "product",
    }
    put_skew_rich = iv_skew is None or iv_skew >= 0.01

    proposals: list[StrategyProposal] = []

    def add(
        strategy_type: str,
        structure: str,
        strike_zone: str,
        expiry: str,
        legs: list[dict[str, Any]],
        thesis: str,
        max_loss: str,
        max_gain: str,
        breakeven: str,
        when_it_wins: str,
        when_it_loses: str,
        degen: int,
        risk: str,
        iv_note: str,
        expiry_dte: Optional[int] = None,
    ) -> None:
        meta = STRATEGY_CATALOG[strategy_type]
        dte_for_score = expiry_dte if expiry_dte is not None else front_dte
        if dte_for_score is not None and dte_for_score <= 5:
            degen = min(degen + 1, 5)
        if liquidity_note:
            risk = f"{risk} · {liquidity_note}" if risk else liquidity_note
        proposals.append(
            StrategyProposal(
                ticker=ticker,
                strategy_type=strategy_type,
                direction=meta["direction"],
                structure=structure,
                strike_zone=strike_zone,
                expiry=expiry,
                legs=legs,
                edge=meta["edge"],
                thesis=thesis,
                iv_note=iv_note,
                max_loss=max_loss,
                max_gain=max_gain,
                breakeven=breakeven,
                when_it_wins=when_it_wins,
                when_it_loses=when_it_loses,
                degen_score=max(1, min(degen, 5)),
                risk_note=risk,
                regime=regime,
            )
        )

    # --- Bullish structures ---
    if bias in {"bullish", "neutral"}:
        if regime == "elevated":
            atm = directional["atm_call"]
            short = directional["otm_call"]
            width = short - atm
            legs = [
                _leg("buy", "call", atm, directional_expiry),
                _leg("sell", "call", short, directional_expiry),
            ]
            debit = picker.net_cost(legs)
            add(
                "debit_call_spread",
                f"Buy {atm:g}C / Sell {short:g}C",
                f"${atm:g}/${short:g} call debit spread",
                directional_expiry,
                legs,
                thesis=f"Bullish but IV is elevated ({iv_pct}) — prefer spread over naked call to cut vega drag",
                max_loss=f"{_fmt(debit)} debit" if debit is not None else "Net debit paid",
                max_gain=(
                    f"{_fmt(width - debit)} (width ${width:g} − debit)"
                    if debit is not None
                    else f"Width ${width:g} minus debit"
                ),
                breakeven=_fmt(atm + debit) if debit is not None else "Long strike + net debit",
                when_it_wins=f"Price pushes through ~{atm:g} toward {short:g}",
                when_it_loses=f"Price stalls/falls below {atm:g} into expiry",
                degen=2,
                risk="Defined risk; still needs directional follow-through before theta wins",
                iv_note=f"{iv_context} — debit spread preferred",
                expiry_dte=directional_dte,
            )
            if can_sell_premium and front["further_otm_put"] is not None:
                short_put = front["otm_put"]
                wing_put = front["further_otm_put"]
                width_p = short_put - wing_put
                legs = [
                    _leg("sell", "put", short_put, nearest_expiry),
                    _leg("buy", "put", wing_put, nearest_expiry),
                ]
                credit = picker.net_cost(legs)
                credit_amt = -credit if credit is not None else None
                add(
                    "credit_put_spread",
                    f"Sell {short_put:g}P / Buy {wing_put:g}P",
                    f"${short_put:g}/${wing_put:g} put credit spread",
                    nearest_expiry,
                    legs,
                    thesis="Bullish/neutral premium collection under support — income if thesis holds",
                    max_loss=(
                        f"{_fmt(width_p - credit_amt)} (width ${width_p:g} − credit)"
                        if credit_amt is not None
                        else f"Width ${width_p:g} minus credit"
                    ),
                    max_gain=f"{_fmt(credit_amt)} credit" if credit_amt is not None else "Net credit received",
                    breakeven=(
                        _fmt(short_put - credit_amt) if credit_amt is not None else "Short put strike − credit"
                    ),
                    when_it_wins=f"Price holds above {short_put:g}",
                    when_it_loses=f"Breakdown through {short_put:g} toward {wing_put:g}",
                    degen=3,
                    risk="Assignment/gap risk through short put; size small around binary events",
                    iv_note="Elevated IV helps credit; still event-gap risk",
                )
        else:
            atm = directional["atm_call"]
            short = front["otm_call"]
            legs = [
                _leg("buy", "call", atm, far_expiry),
                _leg("sell", "call", short, nearest_expiry),
            ]
            debit = picker.net_cost(legs) if far_expiry != nearest_expiry else None
            add(
                "diagonal_call",
                f"Buy {far_expiry} {atm:g}C / Sell {nearest_expiry} {short:g}C",
                f"Diagonal: long {atm:g}C ({far_expiry}) / short {short:g}C ({nearest_expiry})",
                f"{nearest_expiry} → {far_expiry}",
                legs,
                thesis="Bullish with cheaper IV — finance upside with near-term call sale",
                max_loss=f"{_fmt(debit)} net debit (approx)" if debit is not None else "Net debit (approx); varies with early assignment/rolls",
                max_gain="Open-ended-ish vs vertical; depends on roll management",
                breakeven="Dynamic — model before entry",
                when_it_wins="Grind higher while front-month call decays/expires OTM",
                when_it_loses="Sharp dump or front call goes deep ITM without roll",
                degen=3,
                risk="More complex; requires management around pin/assignment",
                iv_note=f"{iv_context} — diagonal/calendar favored over rich debit",
                expiry_dte=back_dte,
            )
            if put_skew_rich:
                short_put = front["otm_put"]
                long_call = front["otm_call"]
                legs = [
                    _leg("sell", "put", short_put, nearest_expiry),
                    _leg("buy", "call", long_call, nearest_expiry),
                ]
                cost = picker.net_cost(legs)
                add(
                    "risk_reversal",
                    f"Sell {short_put:g}P / Buy {long_call:g}C",
                    f"Risk reversal: short {short_put:g}P / long {long_call:g}C",
                    nearest_expiry,
                    legs,
                    thesis="High-conviction bullish synthetic — put sale finances call buy",
                    max_loss="Large if stock collapses below short put (undefined downside)",
                    max_gain=f"Open upside above {long_call:g} (entry {_fmt(cost)})" if cost is not None else "Open upside above long call (minus net debit/plus credit)",
                    breakeven="Depends on net credit/debit at entry",
                    when_it_wins="Sustained upside trend; put expires worthless",
                    when_it_loses="Gap-down through short put",
                    degen=4,
                    risk="Naked downside via short put — only for high conviction + capital",
                    iv_note=(
                        f"Put skew {iv_skew:+.1%} finances the call" if iv_skew is not None
                        else "Works best when put skew is rich relative to calls"
                    ),
                )

    # --- Bearish structures ---
    if bias in {"bearish", "neutral"}:
        if regime == "elevated":
            atm = directional["atm_put"]
            short = directional["otm_put"]
            width = atm - short
            legs = [
                _leg("buy", "put", atm, directional_expiry),
                _leg("sell", "put", short, directional_expiry),
            ]
            debit = picker.net_cost(legs)
            add(
                "debit_put_spread",
                f"Buy {atm:g}P / Sell {short:g}P",
                f"${atm:g}/${short:g} put debit spread",
                directional_expiry,
                legs,
                thesis=f"Bearish with elevated IV ({iv_pct}) — defined-risk put spread vs naked puts",
                max_loss=f"{_fmt(debit)} debit" if debit is not None else "Net debit paid",
                max_gain=(
                    f"{_fmt(width - debit)} (width ${width:g} − debit)"
                    if debit is not None
                    else f"Width ${width:g} minus debit"
                ),
                breakeven=_fmt(atm - debit) if debit is not None else "Long put strike − debit",
                when_it_wins=f"Price breaks below {atm:g} toward {short:g}",
                when_it_loses="Squeeze / bounce holds above long put",
                degen=2,
                risk="Defined risk; needs timely move before theta",
                iv_note=f"{iv_context} — prefer debit put spread",
                expiry_dte=directional_dte,
            )
            if can_sell_premium and front["further_otm_call"] is not None:
                short_call = front["otm_call"]
                wing_call = front["further_otm_call"]
                width_c = wing_call - short_call
                legs = [
                    _leg("sell", "call", short_call, nearest_expiry),
                    _leg("buy", "call", wing_call, nearest_expiry),
                ]
                credit = picker.net_cost(legs)
                credit_amt = -credit if credit is not None else None
                add(
                    "credit_call_spread",
                    f"Sell {short_call:g}C / Buy {wing_call:g}C",
                    f"${short_call:g}/${wing_call:g} call credit spread",
                    nearest_expiry,
                    legs,
                    thesis="Bearish/neutral credit — monetize resistance if rally stalls",
                    max_loss=(
                        f"{_fmt(width_c - credit_amt)} (width ${width_c:g} − credit)"
                        if credit_amt is not None
                        else f"Width ${width_c:g} minus credit"
                    ),
                    max_gain=f"{_fmt(credit_amt)} credit" if credit_amt is not None else "Net credit received",
                    breakeven=(
                        _fmt(short_call + credit_amt) if credit_amt is not None else "Short call + credit"
                    ),
                    when_it_wins=f"Price stays below {short_call:g}",
                    when_it_loses="Breakout squeeze through short call",
                    degen=3,
                    risk="Upside gap risk into short call",
                    iv_note="Credit helped by elevated IV",
                )
        else:
            atm = front["atm_put"]
            legs = [
                _leg("buy", "put", atm, far_expiry),
                _leg("sell", "put", atm, nearest_expiry),
            ]
            debit = picker.net_cost(legs) if far_expiry != nearest_expiry else None
            add(
                "calendar_put",
                f"Buy {far_expiry} {atm:g}P / Sell {nearest_expiry} {atm:g}P",
                f"Put calendar at {atm:g}",
                f"{nearest_expiry} → {far_expiry}",
                legs,
                thesis="Soft-bearish: harvest near-term IV/theta while keeping longer downside optionality",
                max_loss=f"{_fmt(debit)} net debit" if debit is not None else "Net debit",
                max_gain="Best if price pins near ATM into front expiry",
                breakeven="Model-dependent",
                when_it_wins="Front month decays / IV crush while back month retains value",
                when_it_loses="Violent trend away from ATM destroys calendar value",
                degen=3,
                risk="Calendars hate big directional gaps",
                iv_note=iv_context,
                expiry_dte=back_dte,
            )

    # --- Volatility / event structures ---
    if bias == "volatility" or eventy:
        call_strike = front["otm_call"]
        put_strike = front["otm_put"]
        legs = [
            _leg("buy", "put", put_strike, nearest_expiry),
            _leg("buy", "call", call_strike, nearest_expiry),
        ]
        debit = picker.net_cost(legs)
        em_note = f" (expected move ≈ {_fmt(em)})" if em is not None else ""
        add(
            "long_strangle",
            f"Buy {call_strike:g}C + Buy {put_strike:g}P",
            f"Long strangle {put_strike:g}P / {call_strike:g}C",
            nearest_expiry,
            legs,
            thesis=f"Binary/event catalyst — need a large realized move either direction{em_note}",
            max_loss=f"{_fmt(debit)} total debit" if debit is not None else "Total debit of both wings",
            max_gain="Open-ended on a big move",
            breakeven=(
                f"{_fmt(put_strike - debit)} / {_fmt(call_strike + debit)}"
                if debit is not None
                else "Outside each wing by debit amount"
            ),
            when_it_wins="Outsized move beyond wings before theta eats premium",
            when_it_loses="Quiet pin / IV crush without move",
            degen=4 if regime != "cheap" else 3,
            risk="IV crush after events can erase value even if directionally right",
            iv_note=f"Best when IV not already extreme; {iv_context}",
        )
        if far_expiry != nearest_expiry:
            atm = front["atm_call"]
            legs = [
                _leg("buy", "call", atm, far_expiry),
                _leg("sell", "call", atm, nearest_expiry),
            ]
            debit = picker.net_cost(legs)
            add(
                "calendar_call",
                f"Buy {far_expiry} {atm:g}C / Sell {nearest_expiry} {atm:g}C",
                f"Call calendar at {atm:g} through event window",
                f"{nearest_expiry} → {far_expiry}",
                legs,
                thesis="Play post-event IV crush / pin while keeping longer upside optionality",
                max_loss=f"{_fmt(debit)} net debit" if debit is not None else "Net debit",
                max_gain="Front crush + price near ATM",
                breakeven="Model-dependent",
                when_it_wins="Event IV collapses and spot stays near strike",
                when_it_loses="Huge trend move wrecks calendar convexity",
                degen=3,
                risk="Needs event timing alignment with front expiry",
                iv_note="Classic earnings IV-crush structure",
                expiry_dte=back_dte,
            )

    # --- Range / mean-reversion when elevated IV + neutral ---
    if (
        bias == "neutral"
        and regime in {"elevated", "moderate"}
        and can_sell_premium
        and front["further_otm_put"] is not None
        and front["further_otm_call"] is not None
    ):
        short_put, wing_put = front["otm_put"], front["further_otm_put"]
        short_call, wing_call = front["otm_call"], front["further_otm_call"]
        legs = [
            _leg("buy", "put", wing_put, nearest_expiry),
            _leg("sell", "put", short_put, nearest_expiry),
            _leg("sell", "call", short_call, nearest_expiry),
            _leg("buy", "call", wing_call, nearest_expiry),
        ]
        credit = picker.net_cost(legs)
        credit_amt = -credit if credit is not None else None
        width = max(short_put - wing_put, wing_call - short_call)
        add(
            "iron_condor",
            (
                f"Sell {short_put:g}P/{short_call:g}C "
                f"and buy {wing_put:g}P/{wing_call:g}C"
            ),
            f"Iron condor {wing_put:g}/{short_put:g} / {short_call:g}/{wing_call:g}",
            nearest_expiry,
            legs,
            thesis="No clear catalyst edge — sell rich premium inside an expected range",
            max_loss=(
                f"{_fmt(width - credit_amt)} (width ${width:g} − credit)"
                if credit_amt is not None
                else f"Width ${width:g} minus net credit (per side)"
            ),
            max_gain=f"{_fmt(credit_amt)} credit" if credit_amt is not None else "Net credit",
            breakeven=(
                f"{_fmt(short_put - credit_amt)} / {_fmt(short_call + credit_amt)}"
                if credit_amt is not None
                else "Short strikes ± credit"
            ),
            when_it_wins=f"Price stays between {short_put:g} and {short_call:g}",
            when_it_loses="Trend day / gap through either short wing",
            degen=3,
            risk="Avoid into binary events; undefined path risk if unmanaged",
            iv_note=f"{iv_context} supports premium selling",
        )
        atm = front["atm_call"]
        legs = [
            _leg("buy", "put", short_put, nearest_expiry),
            _leg("sell", "put", atm, nearest_expiry),
            _leg("sell", "call", atm, nearest_expiry),
            _leg("buy", "call", short_call, nearest_expiry),
        ]
        credit = picker.net_cost(legs)
        credit_amt = -credit if credit is not None else None
        add(
            "iron_butterfly",
            f"Sell ATM straddle at {atm:g}, buy wings at {short_put:g}/{short_call:g}",
            f"Iron butterfly centered {atm:g}",
            nearest_expiry,
            legs,
            thesis="Expect pin near spot — tighter premium harvest than a wide condor",
            max_loss=(
                f"{_fmt((short_call - atm) - credit_amt)} (wing width − credit)"
                if credit_amt is not None
                else "Width minus credit"
            ),
            max_gain=f"{_fmt(credit_amt)} credit (max at ATM pin)" if credit_amt is not None else "Net credit (max at ATM pin)",
            breakeven=(
                f"{_fmt(atm - credit_amt)} / {_fmt(atm + credit_amt)}"
                if credit_amt is not None
                else "ATM ± credit"
            ),
            when_it_wins=f"Expires near {atm:g}",
            when_it_loses="Any meaningful trend away from ATM",
            degen=3,
            risk="Narrow profit zone; needs disciplined exits",
            iv_note="Favored when expecting quiet tape / pin risk",
        )

    if (
        bias == "bullish"
        and regime == "elevated"
        and can_sell_premium
        and put_skew_rich
        and front["further_otm_call"] is not None
    ):
        short_put = front["otm_put"]
        short_call, wing_call = front["otm_call"], front["further_otm_call"]
        legs = [
            _leg("sell", "put", short_put, nearest_expiry),
            _leg("sell", "call", short_call, nearest_expiry),
            _leg("buy", "call", wing_call, nearest_expiry),
        ]
        credit = picker.net_cost(legs)
        credit_amt = -credit if credit is not None else None
        call_width = wing_call - short_call
        no_upside_risk = credit_amt is not None and credit_amt >= call_width
        add(
            "jade_lizard",
            (
                f"Sell {short_put:g}P + sell {short_call:g}C / "
                f"buy {wing_call:g}C"
            ),
            f"Jade lizard: short {short_put:g}P + {short_call:g}/{wing_call:g} call credit",
            nearest_expiry,
            legs,
            thesis="Bullish premium stack — no upside risk if total credit ≥ call spread width",
            max_loss="Downside via short put (large); upside capped/defined by call spread",
            max_gain=f"{_fmt(credit_amt)} total credit" if credit_amt is not None else "Total credit",
            breakeven=_fmt(short_put - credit_amt) if credit_amt is not None else "Short put − total credit",
            when_it_wins="Sideways-to-up tape; both short options decay",
            when_it_loses="Hard selloff through short put",
            degen=4,
            risk="Still naked-ish downside — capital intensive",
            iv_note=(
                f"Credit {_fmt(credit_amt)} vs call width ${call_width:g} — "
                + ("upside risk eliminated" if no_upside_risk else "upside not fully covered")
                if credit_amt is not None
                else "Requires sufficient credit vs call width"
            ),
        )

    # Prefer structures matching bias, then degen ascending for practicality
    bias_rank = {"bullish": 0, "bearish": 0, "volatility": 0, "neutral": 1}
    proposals.sort(
        key=lambda p: (
            0 if p.direction == bias or (bias == "volatility" and p.direction == "volatility") else 1,
            bias_rank.get(p.direction, 2),
            p.degen_score,
        )
    )

    # Deduplicate by strategy_type
    seen: set[str] = set()
    unique: list[StrategyProposal] = []
    for p in proposals:
        if p.strategy_type in seen:
            continue
        seen.add(p.strategy_type)
        unique.append(p)
        if len(unique) >= limit:
            break
    return unique


def proposals_to_play_dicts(proposals: list[StrategyProposal]) -> list[dict[str, Any]]:
    return [
        {
            "ticker": p.ticker,
            "direction": p.direction,
            "strategy_type": p.strategy_type,
            "structure": p.structure,
            "strike_zone": p.strike_zone,
            "expiry": p.expiry,
            "legs": p.legs,
            "thesis": p.thesis,
            "edge": p.edge,
            "iv_note": p.iv_note,
            "max_loss": p.max_loss,
            "max_gain": p.max_gain,
            "breakeven": p.breakeven,
            "when_it_wins": p.when_it_wins,
            "when_it_loses": p.when_it_loses,
            "degen_score": p.degen_score,
            "risk_note": p.risk_note,
        }
        for p in proposals
    ]
