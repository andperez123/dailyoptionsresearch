from __future__ import annotations

import re

TICKER_PATTERN = re.compile(r"\$?([A-Z]{1,5})\b")
COMMON_WORDS = {
    "A",
    "AI",
    "ALL",
    "AM",
    "AN",
    "AND",
    "ARE",
    "AS",
    "AT",
    "BE",
    "BIG",
    "BUY",
    "CEO",
    "CFO",
    "DD",
    "DOW",
    "EPS",
    "ETF",
    "EU",
    "EV",
    "FDA",
    "FOR",
    "GDP",
    "GO",
    "HAS",
    "HE",
    "HER",
    "HIS",
    "HOD",
    "IMO",
    "IPO",
    "IT",
    "ITS",
    "IV",
    "LOL",
    "LOW",
    "ME",
    "MY",
    "NEW",
    "NOT",
    "NOW",
    "OF",
    "ON",
    "OR",
    "OTM",
    "OUR",
    "OUT",
    "PM",
    "PUT",
    "RSI",
    "SEC",
    "SEE",
    "SO",
    "SPY",
    "THE",
    "TO",
    "TOP",
    "UP",
    "USA",
    "US",
    "VS",
    "WE",
    "WHO",
    "WHY",
    "YOLO",
    "YOU",
}


def extract_tickers(text: str) -> list[str]:
    candidates = set(TICKER_PATTERN.findall(text.upper()))
    return sorted(t for t in candidates if t not in COMMON_WORDS and 1 < len(t) <= 5)


def extract_ticker_set(text: str) -> set[str]:
    return set(extract_tickers(text))
