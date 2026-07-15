from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class SourceLink(BaseModel):
    title: str
    url: str
    source_type: str = "reddit"


class OptionsPlay(BaseModel):
    ticker: str
    direction: str
    strike_zone: str
    expiry: str
    iv_note: str = ""
    degen_score: int = Field(ge=1, le=5)
    risk_note: str = ""


class Narrative(BaseModel):
    title: str
    tickers: list[str]
    story: str
    why_now: str
    bull_case: str
    bear_case: str
    catalysts: list[str] = Field(default_factory=list)
    degen_score: int = Field(ge=1, le=5)
    options_plays: list[OptionsPlay] = Field(default_factory=list)
    sources: list[SourceLink] = Field(default_factory=list)


class SportsAngle(BaseModel):
    model_config = {"extra": "ignore"}

    title: str
    sport: str
    matchup: str
    narrative: str
    why_now: str = ""
    line_note: str = ""
    priced_in: str = ""
    confirmation_points: list[str] = Field(default_factory=list)
    invalidation_points: list[str] = Field(default_factory=list)
    source_event_key: str = ""
    degen_score: int = Field(ge=1, le=5)
    sources: list[SourceLink] = Field(default_factory=list)


class RadarItem(BaseModel):
    ticker: str
    buzz_delta: float = 0.0
    mention_count: int = 0
    note: str = ""


class BriefingContent(BaseModel):
    summary: str
    narratives: list[Narrative] = Field(default_factory=list)
    sports_angles: list[SportsAngle] = Field(default_factory=list)
    radar: list[RadarItem] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    raw_stats: dict[str, Any] = Field(default_factory=dict)
    research_metadata: dict[str, Any] = Field(default_factory=dict)


class BriefingRecord(BaseModel):
    id: int
    briefing_date: date
    content: BriefingContent
    created_at: datetime


class BriefingSummary(BaseModel):
    id: int
    briefing_date: date
    summary: str
    narrative_count: int
    created_at: datetime


class ResearchStatus(BaseModel):
    running: bool
    last_run: Optional[datetime] = None
    last_error: Optional[str] = None
    message: str = ""


# --- V2 Catalyst Intelligence Models ---

Direction = str
CatalystType = str
StrategyClassification = str
HalfLife = str


class RawHeadlineRecord(BaseModel):
    id: int
    provider: str
    external_id: str
    headline: str
    summary: str
    url: str
    published_at: datetime
    content_hash: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class CatalystClusterRecord(BaseModel):
    id: int
    cluster_key: str
    canonical_title: str
    primary_ticker: Optional[str] = None
    first_detected: datetime
    last_updated: datetime
    supporting_source_count: int = 1
    status: str = "active"


class ScoredCatalyst(BaseModel):
    id: int
    cluster_id: Optional[int] = None
    headline: str
    summary: str
    source_name: str
    source_url: str
    published_at: datetime
    detected_at: datetime
    primary_ticker: Optional[str] = None
    related_tickers: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    direction: str = "neutral"
    catalyst_type: str = "other"
    impact_score: int = Field(default=0, ge=0, le=10)
    confidence_score: int = Field(default=0, ge=0, le=10)
    novelty_score: int = Field(default=0, ge=0, le=10)
    current_market_reaction: Optional[str] = None
    thesis: str = ""
    confirmation_signals: list[str] = Field(default_factory=list)
    invalidation_signals: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    strategy_classification: str = "event_watchlist"
    half_life: str = "intraday"
    supporting_source_count: int = 1
    market_reaction_snapshot: dict[str, Any] = Field(default_factory=dict)
    model_version: str = "catalyst-v1"
    scoring_version: str = "score-v1"
    scored: bool = True


class MarketSnapshot(BaseModel):
    symbol: str
    price: Optional[float] = None
    pct_change: Optional[float] = None
    volume: Optional[int] = None
    relative_volume: Optional[float] = None
    implied_volatility: Optional[float] = None
    snapshot_at: datetime
    provider: str = "yfinance"


class PulseResponse(BaseModel):
    indices: list[MarketSnapshot] = Field(default_factory=list)
    sectors: list[MarketSnapshot] = Field(default_factory=list)
    market_status: str = "unknown"
    data_freshness: datetime
    provider_warnings: list[str] = Field(default_factory=list)


class CalendarEvent(BaseModel):
    ticker: Optional[str] = None
    event_type: str
    title: str
    event_date: date
    iv_level: Optional[str] = None
    recent_catalyst_score: Optional[int] = None
    recent_price_change: Optional[float] = None
    vol_context: Optional[str] = None


class DeepDiveResponse(BaseModel):
    ticker: str
    price_snapshot: Optional[MarketSnapshot] = None
    options_snapshot: dict[str, Any] = Field(default_factory=dict)
    recent_catalysts: list[ScoredCatalyst] = Field(default_factory=list)
    upcoming_events: list[CalendarEvent] = Field(default_factory=list)
    social_momentum: dict[str, Any] = Field(default_factory=dict)
    bull_case: str = ""
    bear_case: str = ""
    confirmation_levels: list[str] = Field(default_factory=list)
    invalidation_levels: list[str] = Field(default_factory=list)
    data_quality_warnings: list[str] = Field(default_factory=list)
    ai_analysis: str = ""
    generated_at: datetime
    cached_until: datetime


class SportsNewsContext(BaseModel):
    title: str
    url: str
    source: str = ""
    published: str = ""
    matched_teams: list[str] = Field(default_factory=list)


class SportsOddsLine(BaseModel):
    bookmaker: str
    market: str
    outcomes: list[dict[str, Any]] = Field(default_factory=list)


class SportsGameCard(BaseModel):
    event_key: str = ""
    sport: str
    sport_key: str = ""
    sport_title: str = ""
    home_team: str
    away_team: str
    commence_time: str
    lines: list[SportsOddsLine] = Field(default_factory=list)
    best_line: Optional[dict[str, Any]] = None
    opening_line: Optional[dict[str, Any]] = None
    line_movement: Optional[str] = None
    movement_delta: Optional[str] = None
    fair_line: Optional[list[dict[str, Any]]] = None
    relevance_score: float = 0.0
    relevance_factors: dict[str, float] = Field(default_factory=dict)
    is_live_window: bool = False
    news_context: list[SportsNewsContext] = Field(default_factory=list)
    ai_context: Optional[str] = None
    data_timestamp: datetime


class SportsBoardResponse(BaseModel):
    games: list[SportsGameCard] = Field(default_factory=list)
    configured: bool = False
    message: str = ""
    data_timestamp: datetime
    featured_competitions: list[str] = Field(default_factory=list)
    active_sports_count: int = 0
    quota_remaining: Optional[int] = None
    quota_used: Optional[int] = None


class CatalystFeedbackRequest(BaseModel):
    label: str
    notes: str = ""


class CatalystFeedbackRecord(BaseModel):
    id: int
    catalyst_id: int
    label: str
    notes: str
    created_at: datetime


class WireResponse(BaseModel):
    items: list[ScoredCatalyst]
    total: int
    page: int
    page_size: int

