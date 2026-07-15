from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    finnhub_api_key: str = ""
    fred_api_key: str = ""
    odds_api_key: str = ""
    api_secret: str = ""
    sec_user_agent: str = "DegenResearchBot/1.0 (research@localhost)"
    database_path: str = str(ROOT_DIR / "data" / "briefings.db")
    openai_model_mini: str = "gpt-4o-mini"
    openai_model: str = "gpt-4o"
    reddit_user_agent: str = "DegenResearchBot/1.0 (personal research tool)"
    max_tickers: int = 15

    news_scan_interval_minutes: int = 15
    market_scan_interval_minutes: int = 10
    deep_dive_cache_minutes: int = 15
    daily_briefing_hour: int = 8
    minimum_wire_impact_score: int = 5
    minimum_wire_confidence_score: int = 5
    calendar_scan_interval_hours: int = 4
    sports_scan_interval_minutes: int = 60
    catalyst_model_version: str = "catalyst-v1"
    catalyst_scoring_version: str = "score-v1"
    news_max_age_hours: int = 48
    odds_dynamic_discovery: bool = True
    odds_regions: str = "us"
    odds_max_sports_per_scan: int = 8
    odds_max_events: int = 24
    odds_max_bookmakers_briefing: int = 3
    odds_league_interest_bias: dict[str, float] = {}
    openai_use_web_search: bool = True
    openai_web_search_context: str = "medium"
    openai_deep_research_enabled: bool = False
    openai_max_tool_calls: int = 12

    reddit_subreddits: list[str] = [
        "wallstreetbets",
        "options",
        "stocks",
        "Shortsqueeze",
        "sportsbook",
        "sportsbetting",
    ]
    finance_subreddits: list[str] = [
        "wallstreetbets",
        "options",
        "stocks",
        "Shortsqueeze",
    ]
    sports_subreddits: list[str] = [
        "sportsbook",
        "sportsbetting",
        "soccer",
        "worldcup",
    ]

    pulse_symbols: list[str] = ["SPY", "QQQ", "^VIX", "XLK", "XLF", "XLE"]
    sector_etfs: list[str] = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLB", "XLC"]


settings = Settings()
