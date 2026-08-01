import { useState } from 'react'
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
  const [open, setOpen] = useState(false)
  const thesis = catalyst.thesis || catalyst.summary

  return (
    <article className="border-b border-research-line last:border-b-0">
      <div className="flex items-start gap-3 px-1 py-4">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="min-w-0 flex-1 text-left"
        >
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <ScoreBadge label="IMP" score={catalyst.impact_score} />
            <ScoreBadge label="CONF" score={catalyst.confidence_score} />
            <DirectionBadge direction={catalyst.direction} />
          </div>
          <h3 className="text-[15px] font-semibold leading-snug text-research-ink">
            {catalyst.headline}
          </h3>
          {!open && thesis && (
            <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-research-muted">{thesis}</p>
          )}
        </button>

        <div className="flex shrink-0 flex-col items-end gap-2">
          {catalyst.primary_ticker && (
            <button
              type="button"
              onClick={() => onTickerClick(catalyst.primary_ticker!)}
              className="rounded-full bg-research-green-soft px-2.5 py-1 font-mono text-xs font-semibold text-research-green transition hover:bg-research-green hover:text-white"
            >
              ${catalyst.primary_ticker}
            </button>
          )}
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="text-xs text-research-muted hover:text-research-ink"
          >
            {open ? 'Less' : 'More'}
          </button>
        </div>
      </div>

      {open && (
        <div className="animate-fade-up space-y-3 px-1 pb-5">
          {thesis && <p className="text-sm leading-6 text-research-ink">{thesis}</p>}

          {catalyst.current_market_reaction && (
            <p className="text-sm text-research-muted">
              Market · {catalyst.current_market_reaction}
            </p>
          )}

          {(catalyst.confirmation_signals.length > 0 ||
            catalyst.invalidation_signals.length > 0) && (
            <div className="grid gap-2 sm:grid-cols-2">
              {catalyst.confirmation_signals.length > 0 && (
                <div className="rounded-xl bg-research-green-soft/60 px-3 py-2.5 text-sm">
                  <p className="mb-1 text-xs font-semibold text-research-green">Confirm</p>
                  <p className="text-research-ink">
                    {catalyst.confirmation_signals.slice(0, 2).join(' · ')}
                  </p>
                </div>
              )}
              {catalyst.invalidation_signals.length > 0 && (
                <div className="rounded-xl bg-research-red-soft/60 px-3 py-2.5 text-sm">
                  <p className="mb-1 text-xs font-semibold text-research-red">Invalidate</p>
                  <p className="text-research-ink">
                    {catalyst.invalidation_signals.slice(0, 2).join(' · ')}
                  </p>
                </div>
              )}
            </div>
          )}

          {catalyst.related_tickers.filter((t) => t !== catalyst.primary_ticker).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {catalyst.related_tickers
                .filter((t) => t !== catalyst.primary_ticker)
                .map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => onTickerClick(t)}
                    className="rounded-full bg-research-bg px-2.5 py-1 font-mono text-xs font-semibold text-research-ink hover:bg-research-line"
                  >
                    ${t}
                  </button>
                ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 text-xs text-research-muted">
            <span>{formatStrategy(catalyst.strategy_classification)}</span>
            <span>·</span>
            <span>{catalyst.catalyst_type.replace(/_/g, ' ')}</span>
            <span>·</span>
            <a
              href={catalyst.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-research-blue hover:underline"
            >
              {catalyst.source_name} · {formatTime(catalyst.published_at)}
            </a>
          </div>

          {onFeedback && (
            <div className="flex items-center gap-3 pt-1">
              {['useful', 'noise'].map((label) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => onFeedback(catalyst.id, label)}
                  disabled={Boolean(feedbackLabel)}
                  className="text-xs font-medium capitalize text-research-muted hover:text-research-ink disabled:opacity-40"
                >
                  {label}
                </button>
              ))}
              {feedbackLabel && (
                <span className="text-xs text-research-green">Marked {feedbackLabel}</span>
              )}
            </div>
          )}
        </div>
      )}
    </article>
  )
}
