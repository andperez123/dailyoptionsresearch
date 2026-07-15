from __future__ import annotations

from typing import Any, Optional


def american_to_decimal(price: float) -> float:
    if price == 0:
        return 0.0
    if price > 0:
        return 1.0 + (price / 100.0)
    return 1.0 + (100.0 / abs(price))


def american_to_implied_prob(price: float) -> float:
    decimal = american_to_decimal(price)
    if decimal <= 0:
        return 0.0
    return 1.0 / decimal


def remove_vig(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Multiplicative vig removal for a single market's outcomes."""
    if not outcomes:
        return []
    implied = [american_to_implied_prob(float(o.get("price", 0))) for o in outcomes]
    total = sum(implied)
    if total <= 0:
        return outcomes
    fair: list[dict[str, Any]] = []
    for outcome, raw_prob in zip(outcomes, implied):
        fair_prob = raw_prob / total
        fair.append({**outcome, "fair_probability": round(fair_prob, 4)})
    return fair


def best_price_for_outcome(outcomes: list[dict[str, Any]], name: str) -> Optional[dict[str, Any]]:
    matches = [o for o in outcomes if o.get("name") == name]
    if not matches:
        return None
    return max(matches, key=lambda o: float(o.get("price", -99999)))


def best_h2h_line(lines: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Pick best price per outcome across bookmakers for h2h market."""
    by_name: dict[str, dict[str, Any]] = {}
    for line in lines:
        if line.get("market") != "h2h":
            continue
        bookmaker = line.get("bookmaker", "")
        for outcome in line.get("outcomes", []):
            name = outcome.get("name")
            if not name:
                continue
            price = float(outcome.get("price", 0))
            current = by_name.get(name)
            if current is None or price > float(current.get("price", -99999)):
                by_name[name] = {
                    "name": name,
                    "price": price,
                    "bookmaker": bookmaker,
                }
    if not by_name:
        return None
    outcomes = list(by_name.values())
    return {
        "bookmaker": "best_across_books",
        "outcomes": outcomes,
        "fair_outcomes": remove_vig(outcomes),
    }


def line_movement_delta(
    opening: Optional[dict[str, Any]],
    current: Optional[dict[str, Any]],
) -> Optional[str]:
    if not opening or not current:
        return None
    opening_outcomes = {
        o.get("name"): float(o.get("price", 0))
        for o in opening.get("outcomes", [])
        if o.get("name")
    }
    current_outcomes = {
        o.get("name"): float(o.get("price", 0))
        for o in current.get("outcomes", [])
        if o.get("name")
    }
    deltas: list[str] = []
    for name, current_price in current_outcomes.items():
        opening_price = opening_outcomes.get(name)
        if opening_price is None or opening_price == current_price:
            continue
        deltas.append(f"{name}: {opening_price:+.0f} -> {current_price:+.0f}")
    if not deltas:
        return None
    return "; ".join(deltas)
