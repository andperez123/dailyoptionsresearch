export interface SourceLink {
  title: string
  url: string
  source_type: string
}

export interface OptionsPlay {
  ticker: string
  direction: string
  strike_zone: string
  expiry: string
  iv_note: string
  degen_score: number
  risk_note: string
}

export interface Narrative {
  title: string
  tickers: string[]
  story: string
  why_now: string
  bull_case: string
  bear_case: string
  catalysts: string[]
  degen_score: number
  options_plays: OptionsPlay[]
  sources: SourceLink[]
}

export interface SportsAngle {
  title: string
  sport: string
  matchup: string
  narrative: string
  why_now?: string
  line_note: string
  priced_in?: string
  confirmation_points?: string[]
  invalidation_points?: string[]
  source_event_key?: string
  degen_score: number
  sources: SourceLink[]
}

export interface RadarItem {
  ticker: string
  buzz_delta: number
  mention_count: number
  note: string
}

export interface BriefingContent {
  summary: string
  narratives: Narrative[]
  sports_angles: SportsAngle[]
  radar: RadarItem[]
  generated_at: string
  raw_stats: Record<string, unknown>
  research_metadata?: Record<string, unknown>
}

export interface BriefingRecord {
  id: number
  briefing_date: string
  content: BriefingContent
  created_at: string
}

export interface BriefingSummary {
  id: number
  briefing_date: string
  summary: string
  narrative_count: number
  created_at: string
}

export interface CatalystFeedbackRecord {
  id: number
  catalyst_id: number
  label: string
  notes: string
  created_at: string
}

export interface OptionsSnapshot {
  ticker: string
  current_price: number | null
  nearest_expiry: string | null
  avg_iv: number | null
  put_call_volume_ratio: number | null
  notable_calls: Array<{
    strike: number
    volume: number
    open_interest: number
    implied_volatility: number | null
  }>
  notable_puts: Array<{
    strike: number
    volume: number
    open_interest: number
    implied_volatility: number | null
  }>
  error: string | null
}

export interface ScoredCatalyst {
  id: number
  cluster_id: number | null
  headline: string
  summary: string
  source_name: string
  source_url: string
  published_at: string
  detected_at: string
  primary_ticker: string | null
  related_tickers: string[]
  sectors: string[]
  direction: string
  catalyst_type: string
  impact_score: number
  confidence_score: number
  novelty_score: number
  current_market_reaction: string | null
  thesis: string
  confirmation_signals: string[]
  invalidation_signals: string[]
  key_risks: string[]
  strategy_classification: string
  half_life: string
  supporting_source_count: number
  market_reaction_snapshot: Record<string, unknown>
  model_version: string
  scoring_version: string
  scored: boolean
}

export interface WireResponse {
  items: ScoredCatalyst[]
  total: number
  page: number
  page_size: number
}

export interface MarketSnapshot {
  symbol: string
  price: number | null
  pct_change: number | null
  volume: number | null
  relative_volume: number | null
  implied_volatility: number | null
  snapshot_at: string
  provider: string
}

export interface PulseResponse {
  indices: MarketSnapshot[]
  sectors: MarketSnapshot[]
  market_status: string
  data_freshness: string
  provider_warnings: string[]
}

export interface CalendarEvent {
  ticker: string | null
  event_type: string
  title: string
  event_date: string
  iv_level: string | null
  recent_catalyst_score: number | null
  recent_price_change: number | null
  vol_context: string | null
}

export interface DeepDiveResponse {
  ticker: string
  price_snapshot: MarketSnapshot | null
  options_snapshot: {
    nearest_expiry?: string | null
    avg_iv?: number | null
    put_call_volume_ratio?: number | null
    notable_calls?: Array<Record<string, unknown>>
    notable_puts?: Array<Record<string, unknown>>
    error?: string | null
  }
  recent_catalysts: ScoredCatalyst[]
  upcoming_events: CalendarEvent[]
  social_momentum: {
    mention_count?: number
    note?: string
  }
  bull_case: string
  bear_case: string
  confirmation_levels: string[]
  invalidation_levels: string[]
  data_quality_warnings: string[]
  ai_analysis: string
  generated_at: string
  cached_until: string
}

export interface SportsNewsContext {
  title: string
  url: string
  source: string
  published: string
  matched_teams: string[]
}

export interface SportsOddsLine {
  bookmaker: string
  market: string
  outcomes: Array<{ name: string; price: number; point?: number }>
}

export interface SportsGameCard {
  event_key: string
  sport: string
  sport_key: string
  sport_title: string
  home_team: string
  away_team: string
  commence_time: string
  lines: SportsOddsLine[]
  best_line: Record<string, unknown> | null
  opening_line: Record<string, unknown> | null
  line_movement: string | null
  movement_delta: string | null
  fair_line: Array<Record<string, unknown>> | null
  relevance_score: number
  relevance_factors: Record<string, number>
  is_live_window: boolean
  news_context: SportsNewsContext[]
  ai_context: string | null
  data_timestamp: string
}

export interface SportsBoardResponse {
  games: SportsGameCard[]
  configured: boolean
  message: string
  data_timestamp: string
  featured_competitions: string[]
  active_sports_count: number
  quota_remaining: number | null
  quota_used: number | null
}

export interface ResearchStatus {
  running: boolean
  last_run: string | null
  last_error: string | null
  message: string
}
