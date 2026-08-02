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
    # gpt-5.6 routes to gpt-5.6-sol (flagship); luna is the high-volume tier
    openai_model_mini: str = "gpt-5.6-luna"
    openai_model: str = "gpt-5.6"
    openai_reasoning_effort: str = "medium"
    reddit_user_agent: str = "DegenResearchBot/1.0 (personal research tool)"
    max_tickers: int = 15
    buzz_baseline_days: int = 7

    # Options strategy engine
    options_min_front_dte: int = 5
    options_min_back_dte: int = 25
    options_min_leg_open_interest: int = 50
    options_max_leg_spread_pct: float = 15.0

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
    briefing_news_max_age_hours: int = 24
    min_independent_sources: int = 2
    require_multi_source_narratives: bool = True
    # Narrative threads: days without a fresh narrative before a thread goes stale,
    # and how many active-thread tickers get force-included in the watchlist.
    thread_stale_days: int = 5
    thread_max_tracked: int = 10
    odds_dynamic_discovery: bool = True
    odds_regions: str = "us"
    odds_max_sports_per_scan: int = 8
    odds_max_events: int = 24
    odds_max_bookmakers_briefing: int = 3
    odds_league_interest_bias: dict[str, float] = {}
    # Sports bet decision engine
    sports_bet_horizon_days: int = 3
    sports_min_edge_pct: float = 2.0
    sports_min_ev_pct: float = 3.0
    sports_min_books_for_decision: int = 3
    sports_kelly_multiplier: float = 0.25
    sports_max_stake_units: float = 3.0
    sports_require_edge_persistence: bool = True
    sports_persistence_min_minutes: int = 30
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
