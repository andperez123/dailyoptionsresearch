import { useEffect, useState } from 'react'
import { getDeepDive } from '../api'
import type { DeepDiveResponse } from '../types'
import { formatTime } from '../lib/format'

interface DeepDiveDrawerProps {
  ticker: string | null
  onClose: () => void
}

export function DeepDiveDrawer({ ticker, onClose }: DeepDiveDrawerProps) {
  const [data, setData] = useState<DeepDiveResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!ticker) {
      setData(null)
      setError(null)
      return
    }

    const controller = new AbortController()
    setLoading(true)
    setData(null)
    setError(null)

    getDeepDive(ticker, controller.signal)
      .then(setData)
      .catch((err) => {
        if (err instanceof Error && err.name !== 'AbortError') {
          setError(err.message)
        }
      })
      .finally(() => setLoading(false))

    return () => controller.abort()
  }, [ticker])

  useEffect(() => {
    if (!ticker) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [ticker, onClose])

  if (!ticker) return null

  const pct = data?.price_snapshot?.pct_change
  const up = (pct ?? 0) >= 0

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-research-ink/20 backdrop-blur-[2px]" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${ticker} research`}
        className="animate-slide-in h-full w-full max-w-md overflow-y-auto bg-research-surface shadow-sheet"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-research-line bg-research-surface/95 px-5 py-4 backdrop-blur">
          <h2 className="font-mono text-xl font-bold tracking-tight">${ticker}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-full px-2 py-1 text-sm text-research-muted hover:bg-research-bg hover:text-research-ink"
          >
            Close
          </button>
        </div>

        <div className="space-y-6 px-5 py-6">
          {loading && (
            <p className="animate-pulse text-sm text-research-muted">Loading research…</p>
          )}
          {error && <p className="text-sm text-research-red">{error}</p>}

          {data && (
            <>
              <section>
                {data.price_snapshot ? (
                  <div>
                    <p className="font-mono text-4xl font-semibold tracking-tight tabular-nums">
                      ${data.price_snapshot.price?.toFixed(2)}
                    </p>
                    <p
                      className={`mt-1 font-mono text-lg font-semibold tabular-nums ${
                        up ? 'text-research-green' : 'text-research-red'
                      }`}
                    >
                      {up ? '+' : ''}
                      {pct?.toFixed(2)}%
                      {data.price_snapshot.relative_volume != null && (
                        <span className="ml-2 text-sm font-medium text-research-muted">
                          {data.price_snapshot.relative_volume}x vol
                        </span>
                      )}
                    </p>
                    <p className="mt-2 text-xs text-research-muted">
                      {formatTime(data.price_snapshot.snapshot_at)} · {data.price_snapshot.provider}
                    </p>
                  </div>
                ) : (
                  <p className="text-sm text-research-muted">No price data</p>
                )}
              </section>

              <section className="grid grid-cols-3 gap-3">
                {[
                  {
                    label: 'Expiry',
                    value: data.options_snapshot.nearest_expiry || '—',
                  },
                  {
                    label: 'Avg IV',
                    value:
                      data.options_snapshot.avg_iv != null
                        ? String(data.options_snapshot.avg_iv)
                        : '—',
                  },
                  {
                    label: 'P/C',
                    value:
                      data.options_snapshot.put_call_volume_ratio != null
                        ? String(data.options_snapshot.put_call_volume_ratio)
                        : '—',
                  },
                ].map((stat) => (
                  <div key={stat.label} className="rounded-2xl bg-research-bg px-3 py-3">
                    <p className="text-xs text-research-muted">{stat.label}</p>
                    <p className="mt-1 font-mono text-sm font-semibold tabular-nums">{stat.value}</p>
                  </div>
                ))}
              </section>

              {(data.bull_case || data.bear_case || data.ai_analysis) && (
                <section className="space-y-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-research-muted">
                    Interpretation
                  </h3>
                  {data.ai_analysis && (
                    <p className="text-sm leading-6 text-research-ink">{data.ai_analysis}</p>
                  )}
                  {data.bull_case && (
                    <div className="rounded-2xl bg-research-green-soft/70 px-4 py-3">
                      <p className="mb-1 text-xs font-semibold text-research-green">Bull</p>
                      <p className="text-sm leading-6">{data.bull_case}</p>
                    </div>
                  )}
                  {data.bear_case && (
                    <div className="rounded-2xl bg-research-red-soft/70 px-4 py-3">
                      <p className="mb-1 text-xs font-semibold text-research-red">Bear</p>
                      <p className="text-sm leading-6">{data.bear_case}</p>
                    </div>
                  )}
                </section>
              )}

              {(data.confirmation_levels.length > 0 || data.invalidation_levels.length > 0) && (
                <section className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-research-muted">
                    Levels
                  </h3>
                  {data.confirmation_levels.map((level) => (
                    <p key={level} className="text-sm text-research-green">
                      {level}
                    </p>
                  ))}
                  {data.invalidation_levels.map((level) => (
                    <p key={level} className="text-sm text-research-red">
                      {level}
                    </p>
                  ))}
                </section>
              )}

              {data.upcoming_events.length > 0 && (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-research-muted">
                    Upcoming
                  </h3>
                  <ul className="space-y-2">
                    {data.upcoming_events.map((event) => (
                      <li
                        key={`${event.event_date}-${event.title}`}
                        className="flex justify-between gap-3 text-sm"
                      >
                        <span className="text-research-ink">{event.title}</span>
                        <span className="shrink-0 font-mono text-xs text-research-muted">
                          {event.event_date}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {data.recent_catalysts.length > 0 && (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-research-muted">
                    Recent catalysts
                  </h3>
                  <ul className="space-y-3">
                    {data.recent_catalysts.slice(0, 5).map((c) => (
                      <li key={c.id} className="text-sm">
                        <span className="font-mono text-xs font-semibold text-research-green">
                          {c.impact_score}
                        </span>
                        <span className="ml-2 text-research-ink">{c.headline}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {data.social_momentum.mention_count != null && (
                <p className="text-sm text-research-muted">
                  Mentions · {data.social_momentum.mention_count}
                  {data.social_momentum.note ? ` · ${data.social_momentum.note}` : ''}
                </p>
              )}

              {data.data_quality_warnings.length > 0 && (
                <div className="rounded-2xl bg-research-amber-soft px-4 py-3 text-sm text-research-amber">
                  {data.data_quality_warnings.map((w) => (
                    <p key={w}>{w}</p>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
