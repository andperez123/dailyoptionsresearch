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


def best_market_line(lines: list[dict[str, Any]], market: str) -> Optional[dict[str, Any]]:
    """Pick best price per outcome name across bookmakers for a market."""
    by_name: dict[str, dict[str, Any]] = {}
    for line in lines:
        if line.get("market") != market:
            continue
        bookmaker = line.get("bookmaker", "")
        for outcome in line.get("outcomes", []):
            name = outcome.get("name")
            if not name:
                continue
            price = float(outcome.get("price", 0))
            current = by_name.get(name)
            if current is None or price > float(current.get("price", -99999)):
                entry = {
                    "name": name,
                    "price": price,
                    "bookmaker": bookmaker,
                }
                if outcome.get("point") is not None:
                    entry["point"] = outcome.get("point")
                by_name[name] = entry
    if not by_name:
        return None
    outcomes = list(by_name.values())
    return {
        "bookmaker": "best_across_books",
        "outcomes": outcomes,
        "fair_outcomes": remove_vig(outcomes),
    }


def best_h2h_line(lines: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Pick best price per outcome across bookmakers for h2h market."""
    return best_market_line(lines, "h2h")


def line_movement_delta(
    opening: Optional[dict[str, Any]],
    current: Optional[dict[str, Any]],
) -> Optional[str]:
    if not opening or not current:
        return None

    def _index(line: dict[str, Any]) -> dict[str, tuple[float, Optional[float]]]:
        indexed: dict[str, tuple[float, Optional[float]]] = {}
        for o in line.get("outcomes", []):
            name = o.get("name")
            if not name:
                continue
            point = o.get("point")
            indexed[name] = (float(o.get("price", 0)), float(point) if point is not None else None)
        return indexed

    opening_outcomes = _index(opening)
    current_outcomes = _index(current)
    deltas: list[str] = []
    for name, (current_price, current_point) in current_outcomes.items():
        opened = opening_outcomes.get(name)
        if opened is None:
            continue
        opening_price, opening_point = opened
        price_moved = opening_price != current_price
        point_moved = (
            opening_point is not None
            and current_point is not None
            and opening_point != current_point
        )
        if not price_moved and not point_moved:
            continue
        if point_moved:
            deltas.append(
                f"{name}: {opening_point:g} ({opening_price:+.0f}) -> "
                f"{current_point:g} ({current_price:+.0f})"
            )
        else:
            deltas.append(f"{name}: {opening_price:+.0f} -> {current_price:+.0f}")
    if not deltas:
        return None
    return "; ".join(deltas)
