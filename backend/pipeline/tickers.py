from __future__ import annotations

import re

TICKER_PATTERN = re.compile(r"\$?([A-Z]{1,5})\b")
CASHTAG_PATTERN = re.compile(r"\$([A-Za-z]{1,5})\b")
COMMON_WORDS = {
    "A",
    "AI",
    "ALL",
    "AM",
    "AN",
    "AND",
    "ANY",
    "ARE",
    "AS",
    "AT",
    "AMP",
    "ATH",
    "BAD",
    "BE",
    "BIG",
    "BR",
    "BUT",
    "BUY",
    "BY",
    # CAN, DAY, ONE, TWO are real (small) tickers, but as bare uppercase
    # words they are overwhelmingly false positives; cashtags still work.
    "CAN",
    "CEO",
    "CFO",
    "COM",
    "CPI",
    "DAY",
    "DD",
    "DID",
    "DIV",
    "DO",
    "DOW",
    "DTE",
    "EOD",
    "EPS",
    "ETF",
    "EU",
    "EV",
    "FED",
    "FDA",
    "FOR",
    "FYI",
    "GDP",
    "GET",
    "GO",
    "GOT",
    "HAD",
    "HAS",
    "HE",
    "HER",
    "HIM",
    "HIS",
    "HOD",
    "HOW",
    "IF",
    "IMO",
    "IPO",
    "IS",
    "IT",
    "ITM",
    "ITS",
    "IV",
    # Crypto/abbreviation noise that shadows small listed tickers; explicit
    # $CASHTAGS still match.
    "LINK",
    "LOL",
    "LOW",
    "MD",
    "ME",
    "MOON",
    "MY",
    "NEW",
    "NO",
    "NOT",
    "NOW",
    "OF",
    "OFF",
    "OLD",
    "ON",
    "ONE",
    "OR",
    "OTM",
    "OUR",
    "OUT",
    "OWN",
    "PE",
    "PM",
    "PUT",
    "RSI",
    "SAY",
    "SEC",
    "SEE",
    "SHE",
    "SO",
    "SPY",
    "THE",
    "TO",
    "TOP",
    "TWO",
    "UP",
    "USA",
    "US",
    "VS",
    "WAS",
    "WAY",
    "WE",
    "WHO",
    "WHY",
    "WSB",
    "WWW",
    "YES",
    "YOLO",
    "YOU",
    "YTD",
}


def extract_tickers(text: str) -> list[str]:
    candidates = set(TICKER_PATTERN.findall(text.upper()))
    return sorted(t for t in candidates if t not in COMMON_WORDS and 1 < len(t) <= 5)


def extract_ticker_set(text: str) -> set[str]:
    return set(extract_tickers(text))


def extract_cashtags(text: str) -> set[str]:
    """Explicit $TICK mentions — unambiguous, unlike bare uppercase words."""
    return {
        match.upper()
        for match in CASHTAG_PATTERN.findall(text)
        if 1 < len(match) <= 5 and match.upper() not in COMMON_WORDS
    }
