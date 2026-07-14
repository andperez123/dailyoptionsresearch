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
  line_note: string
  public_vs_sharp: string
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
  nearest_expiry?: string
  avg_iv?: number
  put_call_volume_ratio?: number
  notable_calls?: Array<{ strike: number; volume: number; oi: number }>
  notable_puts?: Array<{ strike: number; volume: number; oi: number }>
  error?: string
}

export interface SocialMomentum {
  mention_count?: number
  note?: string
}

export interface ResearchStatus {
  running: boolean
  last_run: string | null
  last_error: string | null
  message: string
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

export interface WireResponse {
  items: ScoredCatalyst[]
  total: number
  page: number
  page_size: number
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
  options_snapshot: OptionsSnapshot
  recent_catalysts: ScoredCatalyst[]
  upcoming_events: CalendarEvent[]
  social_momentum: SocialMomentum
  bull_case: string
  bear_case: string
  confirmation_levels: string[]
  invalidation_levels: string[]
  data_quality_warnings: string[]
  ai_analysis: string
  generated_at: string
  cached_until: string
}

export interface SportsOddsLine {
  bookmaker: string
  market: string
  outcomes: Array<{ name: string; price: number; point?: number }>
}

export interface SportsGameCard {
  sport: string
  home_team: string
  away_team: string
  commence_time: string
  lines: SportsOddsLine[]
  best_line: Record<string, unknown> | null
  opening_line: Record<string, unknown> | null
  line_movement: string | null
  ai_context: string | null
  data_timestamp: string
}

export interface SportsBoardResponse {
  games: SportsGameCard[]
  configured: boolean
  message: string
  data_timestamp: string
}
