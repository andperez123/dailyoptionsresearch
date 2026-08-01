"""Deterministic multi-leg options strategy proposals from chain + catalyst context."""

from __future__ import annotations

from dataclasses import dataclass
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


def _round_strike(price: float, step: float = 1.0) -> float:
    if price >= 200:
        step = 5.0
    elif price >= 50:
        step = 2.5 if abs(price % 5) in (2.5, 7.5) else 5.0
        if step == 5.0:
            return round(price / 5.0) * 5.0
    elif price >= 20:
        step = 1.0
    else:
        step = 0.5
    return round(price / step) * step


def _atm(price: Optional[float]) -> Optional[float]:
    if price is None or price <= 0:
        return None
    return _round_strike(price)


def _pick_strikes(price: float) -> dict[str, float]:
    atm = _atm(price) or price
    width = 5.0 if price >= 50 else (2.5 if price >= 20 else 1.0)
    if price >= 200:
        width = 10.0
    return {
        "atm": atm,
        "otm_call": atm + width,
        "further_otm_call": atm + 2 * width,
        "otm_put": atm - width,
        "further_otm_put": atm - 2 * width,
        "width": width,
    }


def classify_iv_regime(avg_iv: Optional[float], put_call_ratio: Optional[float]) -> str:
    """Rough IV regime from available chain stats (no true IV rank without history)."""
    if avg_iv is None:
        return "unknown"
    if avg_iv >= 0.55:
        return "elevated"
    if avg_iv >= 0.35:
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
) -> list[StrategyProposal]:
    if price is None or price <= 0 or not nearest_expiry:
        return []

    strikes = _pick_strikes(price)
    regime = classify_iv_regime(avg_iv, put_call_ratio)
    bias = classify_bias(catalyst_direction, put_call_ratio, pct_change)
    far_expiry = next_expiry or nearest_expiry
    atm = strikes["atm"]
    w = strikes["width"]
    iv_pct = f"{avg_iv:.0%}" if avg_iv is not None else "n/a"
    eventy = (catalyst_type or "").lower() in {
        "earnings",
        "guidance",
        "regulatory",
        "merger",
        "legal",
        "product",
    }

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
    ) -> None:
        meta = STRATEGY_CATALOG[strategy_type]
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
                degen_score=degen,
                risk_note=risk,
                regime=regime,
            )
        )

    # --- Bullish structures ---
    if bias in {"bullish", "neutral"}:
        if regime == "elevated":
            add(
                "debit_call_spread",
                f"Buy {atm}C / Sell {strikes['otm_call']}C",
                f"${atm}/${strikes['otm_call']} call debit spread",
                nearest_expiry,
                [
                    {"action": "buy", "option_type": "call", "strike": str(atm), "expiry": nearest_expiry, "quantity": 1},
                    {"action": "sell", "option_type": "call", "strike": str(strikes["otm_call"]), "expiry": nearest_expiry, "quantity": 1},
                ],
                thesis=f"Bullish but IV is elevated ({iv_pct}) — prefer spread over naked call to cut vega drag",
                max_loss="Net debit paid",
                max_gain=f"Width ${w} minus debit",
                breakeven="Long strike + net debit",
                when_it_wins=f"Price pushes through ~{atm} toward {strikes['otm_call']}",
                when_it_loses=f"Price stalls/falls below {atm} into expiry",
                degen=2,
                risk="Defined risk; still needs directional follow-through before theta wins",
                iv_note=f"IV regime={regime} ({iv_pct}) — debit spread preferred",
            )
            add(
                "credit_put_spread",
                f"Sell {strikes['otm_put']}P / Buy {strikes['further_otm_put']}P",
                f"${strikes['otm_put']}/${strikes['further_otm_put']} put credit spread",
                nearest_expiry,
                [
                    {"action": "sell", "option_type": "put", "strike": str(strikes["otm_put"]), "expiry": nearest_expiry, "quantity": 1},
                    {"action": "buy", "option_type": "put", "strike": str(strikes["further_otm_put"]), "expiry": nearest_expiry, "quantity": 1},
                ],
                thesis="Bullish/neutral premium collection under support — income if thesis holds",
                max_loss=f"Width ${w} minus credit",
                max_gain="Net credit received",
                breakeven="Short put strike − credit",
                when_it_wins=f"Price holds above {strikes['otm_put']}",
                when_it_loses=f"Breakdown through {strikes['otm_put']} toward {strikes['further_otm_put']}",
                degen=3,
                risk="Assignment/gap risk through short put; size small around binary events",
                iv_note=f"Elevated IV helps credit; still event-gap risk",
            )
        else:
            add(
                "diagonal_call",
                f"Buy {far_expiry} {atm}C / Sell {nearest_expiry} {strikes['otm_call']}C",
                f"Diagonal: long {atm}C ({far_expiry}) / short {strikes['otm_call']}C ({nearest_expiry})",
                f"{nearest_expiry} → {far_expiry}",
                [
                    {"action": "buy", "option_type": "call", "strike": str(atm), "expiry": far_expiry, "quantity": 1},
                    {"action": "sell", "option_type": "call", "strike": str(strikes["otm_call"]), "expiry": nearest_expiry, "quantity": 1},
                ],
                thesis="Bullish with cheaper IV — finance upside with near-term call sale",
                max_loss="Net debit (approx); varies with early assignment/rolls",
                max_gain="Open-ended-ish vs vertical; depends on roll management",
                breakeven="Dynamic — model before entry",
                when_it_wins="Grind higher while front-month call decays/expires OTM",
                when_it_loses="Sharp dump or front call goes deep ITM without roll",
                degen=3,
                risk="More complex; requires management around pin/assignment",
                iv_note=f"IV regime={regime} — diagonal/calendar favored over rich debit",
            )
            add(
                "risk_reversal",
                f"Sell {strikes['otm_put']}P / Buy {strikes['otm_call']}C",
                f"Risk reversal: short {strikes['otm_put']}P / long {strikes['otm_call']}C",
                nearest_expiry,
                [
                    {"action": "sell", "option_type": "put", "strike": str(strikes["otm_put"]), "expiry": nearest_expiry, "quantity": 1},
                    {"action": "buy", "option_type": "call", "strike": str(strikes["otm_call"]), "expiry": nearest_expiry, "quantity": 1},
                ],
                thesis="High-conviction bullish synthetic — put sale finances call buy",
                max_loss="Large if stock collapses below short put (undefined downside)",
                max_gain="Open upside above long call (minus net debit/plus credit)",
                breakeven="Depends on net credit/debit at entry",
                when_it_wins="Sustained upside trend; put expires worthless",
                when_it_loses="Gap-down through short put",
                degen=4,
                risk="Naked downside via short put — only for high conviction + capital",
                iv_note=f"Works best when put skew is rich relative to calls",
            )

    # --- Bearish structures ---
    if bias in {"bearish", "neutral"}:
        if regime == "elevated":
            add(
                "debit_put_spread",
                f"Buy {atm}P / Sell {strikes['otm_put']}P",
                f"${atm}/${strikes['otm_put']} put debit spread",
                nearest_expiry,
                [
                    {"action": "buy", "option_type": "put", "strike": str(atm), "expiry": nearest_expiry, "quantity": 1},
                    {"action": "sell", "option_type": "put", "strike": str(strikes["otm_put"]), "expiry": nearest_expiry, "quantity": 1},
                ],
                thesis=f"Bearish with elevated IV ({iv_pct}) — defined-risk put spread vs naked puts",
                max_loss="Net debit paid",
                max_gain=f"Width ${w} minus debit",
                breakeven="Long put strike − debit",
                when_it_wins=f"Price breaks below {atm} toward {strikes['otm_put']}",
                when_it_loses="Squeeze / bounce holds above long put",
                degen=2,
                risk="Defined risk; needs timely move before theta",
                iv_note=f"IV regime={regime} — prefer debit put spread",
            )
            add(
                "credit_call_spread",
                f"Sell {strikes['otm_call']}C / Buy {strikes['further_otm_call']}C",
                f"${strikes['otm_call']}/${strikes['further_otm_call']} call credit spread",
                nearest_expiry,
                [
                    {"action": "sell", "option_type": "call", "strike": str(strikes["otm_call"]), "expiry": nearest_expiry, "quantity": 1},
                    {"action": "buy", "option_type": "call", "strike": str(strikes["further_otm_call"]), "expiry": nearest_expiry, "quantity": 1},
                ],
                thesis="Bearish/neutral credit — monetize resistance if rally stalls",
                max_loss=f"Width ${w} minus credit",
                max_gain="Net credit received",
                breakeven="Short call + credit",
                when_it_wins=f"Price stays below {strikes['otm_call']}",
                when_it_loses="Breakout squeeze through short call",
                degen=3,
                risk="Upside gap risk into short call",
                iv_note="Credit helped by elevated IV",
            )
        else:
            add(
                "calendar_put",
                f"Buy {far_expiry} {atm}P / Sell {nearest_expiry} {atm}P",
                f"Put calendar at {atm}",
                f"{nearest_expiry} → {far_expiry}",
                [
                    {"action": "buy", "option_type": "put", "strike": str(atm), "expiry": far_expiry, "quantity": 1},
                    {"action": "sell", "option_type": "put", "strike": str(atm), "expiry": nearest_expiry, "quantity": 1},
                ],
                thesis="Soft-bearish: harvest near-term IV/theta while keeping longer downside optionality",
                max_loss="Net debit",
                max_gain="Best if price pins near ATM into front expiry",
                breakeven="Model-dependent",
                when_it_wins="Front month decays / IV crush while back month retains value",
                when_it_loses="Violent trend away from ATM destroys calendar value",
                degen=3,
                risk="Calendars hate big directional gaps",
                iv_note=f"IV regime={regime}",
            )

    # --- Volatility / event structures ---
    if bias == "volatility" or eventy:
        add(
            "long_strangle",
            f"Buy {strikes['otm_call']}C + Buy {strikes['otm_put']}P",
            f"Long strangle {strikes['otm_put']}P / {strikes['otm_call']}C",
            nearest_expiry,
            [
                {"action": "buy", "option_type": "put", "strike": str(strikes["otm_put"]), "expiry": nearest_expiry, "quantity": 1},
                {"action": "buy", "option_type": "call", "strike": str(strikes["otm_call"]), "expiry": nearest_expiry, "quantity": 1},
            ],
            thesis="Binary/event catalyst — need a large realized move either direction",
            max_loss="Total debit of both wings",
            max_gain="Open-ended on a big move",
            breakeven="Outside each wing by debit amount",
            when_it_wins="Outsized move beyond wings before theta eats premium",
            when_it_loses="Quiet pin / IV crush without move",
            degen=4 if regime != "cheap" else 3,
            risk="IV crush after events can erase value even if directionally right",
            iv_note=f"Best when IV not already extreme; current regime={regime} ({iv_pct})",
        )
        if far_expiry != nearest_expiry:
            add(
                "calendar_call",
                f"Buy {far_expiry} {atm}C / Sell {nearest_expiry} {atm}C",
                f"Call calendar at {atm} through event window",
                f"{nearest_expiry} → {far_expiry}",
                [
                    {"action": "buy", "option_type": "call", "strike": str(atm), "expiry": far_expiry, "quantity": 1},
                    {"action": "sell", "option_type": "call", "strike": str(atm), "expiry": nearest_expiry, "quantity": 1},
                ],
                thesis="Play post-event IV crush / pin while keeping longer upside optionality",
                max_loss="Net debit",
                max_gain="Front crush + price near ATM",
                breakeven="Model-dependent",
                when_it_wins="Event IV collapses and spot stays near strike",
                when_it_loses="Huge trend move wrecks calendar convexity",
                degen=3,
                risk="Needs event timing alignment with front expiry",
                iv_note="Classic earnings IV-crush structure",
            )

    # --- Range / mean-reversion when elevated IV + neutral ---
    if bias == "neutral" and regime in {"elevated", "moderate"}:
        add(
            "iron_condor",
            (
                f"Sell {strikes['otm_put']}P/{strikes['otm_call']}C "
                f"and buy {strikes['further_otm_put']}P/{strikes['further_otm_call']}C"
            ),
            f"Iron condor {strikes['further_otm_put']}/{strikes['otm_put']} / {strikes['otm_call']}/{strikes['further_otm_call']}",
            nearest_expiry,
            [
                {"action": "buy", "option_type": "put", "strike": str(strikes["further_otm_put"]), "expiry": nearest_expiry, "quantity": 1},
                {"action": "sell", "option_type": "put", "strike": str(strikes["otm_put"]), "expiry": nearest_expiry, "quantity": 1},
                {"action": "sell", "option_type": "call", "strike": str(strikes["otm_call"]), "expiry": nearest_expiry, "quantity": 1},
                {"action": "buy", "option_type": "call", "strike": str(strikes["further_otm_call"]), "expiry": nearest_expiry, "quantity": 1},
            ],
            thesis="No clear catalyst edge — sell rich premium inside an expected range",
            max_loss=f"Width ${w} minus net credit (per side)",
            max_gain="Net credit",
            breakeven="Short strikes ± credit",
            when_it_wins=f"Price stays between {strikes['otm_put']} and {strikes['otm_call']}",
            when_it_loses="Trend day / gap through either short wing",
            degen=3,
            risk="Avoid into binary events; undefined path risk if unmanaged",
            iv_note=f"IV regime={regime} supports premium selling",
        )
        add(
            "iron_butterfly",
            f"Sell ATM straddle at {atm}, buy wings at {strikes['otm_put']}/{strikes['otm_call']}",
            f"Iron butterfly centered {atm}",
            nearest_expiry,
            [
                {"action": "buy", "option_type": "put", "strike": str(strikes["otm_put"]), "expiry": nearest_expiry, "quantity": 1},
                {"action": "sell", "option_type": "put", "strike": str(atm), "expiry": nearest_expiry, "quantity": 1},
                {"action": "sell", "option_type": "call", "strike": str(atm), "expiry": nearest_expiry, "quantity": 1},
                {"action": "buy", "option_type": "call", "strike": str(strikes["otm_call"]), "expiry": nearest_expiry, "quantity": 1},
            ],
            thesis="Expect pin near spot — tighter premium harvest than a wide condor",
            max_loss=f"Width ${w} minus credit",
            max_gain="Net credit (max at ATM pin)",
            breakeven="ATM ± credit",
            when_it_wins=f"Expires near {atm}",
            when_it_loses="Any meaningful trend away from ATM",
            degen=3,
            risk="Narrow profit zone; needs disciplined exits",
            iv_note="Favored when expecting quiet tape / pin risk",
        )

    if bias == "bullish" and regime == "elevated":
        add(
            "jade_lizard",
            (
                f"Sell {strikes['otm_put']}P + sell {strikes['otm_call']}C / "
                f"buy {strikes['further_otm_call']}C"
            ),
            f"Jade lizard: short {strikes['otm_put']}P + {strikes['otm_call']}/{strikes['further_otm_call']} call credit",
            nearest_expiry,
            [
                {"action": "sell", "option_type": "put", "strike": str(strikes["otm_put"]), "expiry": nearest_expiry, "quantity": 1},
                {"action": "sell", "option_type": "call", "strike": str(strikes["otm_call"]), "expiry": nearest_expiry, "quantity": 1},
                {"action": "buy", "option_type": "call", "strike": str(strikes["further_otm_call"]), "expiry": nearest_expiry, "quantity": 1},
            ],
            thesis="Bullish premium stack — no upside risk if total credit ≥ call spread width",
            max_loss="Downside via short put (large); upside capped/defined by call spread",
            max_gain="Total credit",
            breakeven="Short put − total credit",
            when_it_wins="Sideways-to-up tape; both short options decay",
            when_it_loses="Hard selloff through short put",
            degen=4,
            risk="Still naked-ish downside — capital intensive",
            iv_note="Requires sufficient credit vs call width",
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
