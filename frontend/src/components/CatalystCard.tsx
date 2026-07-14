import type { ScoredCatalyst } from '../types'
import { DirectionBadge, ScoreBadge, formatStrategy, formatTime } from './ScoreBadge'

interface CatalystCardProps {
  catalyst: ScoredCatalyst
  onTickerClick: (ticker: string) => void
  onFeedback?: (id: number, label: string) => void
  feedbackLabel?: string
}

export function CatalystCard({
  catalyst,
  onTickerClick,
  onFeedback,
  feedbackLabel,
}: CatalystCardProps) {
  return (
    <article className="rounded border border-terminal-border bg-terminal-panel p-3 text-sm transition hover:border-terminal-green/30">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <ScoreBadge label="IMP" score={catalyst.impact_score} />
        <ScoreBadge label="CONF" score={catalyst.confidence_score} />
        <DirectionBadge direction={catalyst.direction} />
        <span className="rounded bg-terminal-bg px-1.5 py-0.5 text-[10px] uppercase text-terminal-muted">
          {catalyst.catalyst_type.replace(/_/g, ' ')}
        </span>
        <span className="text-[10px] text-terminal-muted">{catalyst.half_life.replace(/_/g, ' ')}</span>
        {!catalyst.scored && (
          <span className="text-[10px] text-terminal-yellow">unscored</span>
        )}
      </div>

      <h3 className="mb-1 font-semibold leading-snug text-white">{catalyst.headline}</h3>
      <p className="mb-2 text-xs leading-relaxed text-gray-400">{catalyst.thesis || catalyst.summary}</p>

      {catalyst.current_market_reaction && (
        <p className="mb-2 text-[11px] text-terminal-cyan">
          Market: {catalyst.current_market_reaction}
        </p>
      )}

      {(catalyst.confirmation_signals.length > 0 || catalyst.invalidation_signals.length > 0) && (
        <div className="mb-2 space-y-1 text-[10px]">
          {catalyst.confirmation_signals.length > 0 && (
            <p className="text-terminal-green">
              Confirm: {catalyst.confirmation_signals.slice(0, 2).join(' · ')}
            </p>
          )}
          {catalyst.invalidation_signals.length > 0 && (
            <p className="text-terminal-red">
              Invalidate: {catalyst.invalidation_signals.slice(0, 2).join(' · ')}
            </p>
          )}
        </div>
      )}

      <div className="mb-2 flex flex-wrap gap-1">
        {catalyst.primary_ticker && (
          <button
            onClick={() => onTickerClick(catalyst.primary_ticker!)}
            className="rounded bg-terminal-bg px-2 py-0.5 font-mono text-xs text-terminal-yellow hover:bg-terminal-green/10"
          >
            ${catalyst.primary_ticker}
          </button>
        )}
        {catalyst.related_tickers
          .filter((t) => t !== catalyst.primary_ticker)
          .map((t) => (
            <button
              key={t}
              onClick={() => onTickerClick(t)}
              className="rounded bg-terminal-bg px-2 py-0.5 font-mono text-xs text-terminal-cyan hover:bg-terminal-green/10"
            >
              ${t}
            </button>
          ))}
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-2 text-[10px] text-terminal-muted">
        <span>{formatStrategy(catalyst.strategy_classification)}</span>
        <span>·</span>
        <span>{catalyst.supporting_source_count} source(s)</span>
        <span>·</span>
        <a
          href={catalyst.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-terminal-cyan hover:underline"
        >
          {catalyst.source_name} · {formatTime(catalyst.published_at)}
        </a>
      </div>

      {onFeedback && (
        <div className="flex items-center gap-2 border-t border-terminal-border pt-2">
          {['useful', 'noise'].map((label) => (
            <button
              key={label}
              onClick={() => onFeedback(catalyst.id, label)}
              disabled={Boolean(feedbackLabel)}
              className="text-[10px] uppercase text-terminal-muted hover:text-terminal-green disabled:opacity-50"
            >
              {label}
            </button>
          ))}
          {feedbackLabel && (
            <span className="text-[10px] text-terminal-green">Marked {feedbackLabel}</span>
          )}
        </div>
      )}
    </article>
  )
}
