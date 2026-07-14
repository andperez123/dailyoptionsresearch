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

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${ticker} deep dive`}
        className="h-full w-full max-w-lg overflow-y-auto border-l border-terminal-border bg-terminal-bg p-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold text-terminal-green">${ticker}</h2>
          <button
            onClick={onClose}
            aria-label="Close deep dive"
            className="text-terminal-muted hover:text-white"
          >
            ✕
          </button>
        </div>

        {loading && <p className="animate-pulse text-sm text-terminal-green">Loading deep dive...</p>}
        {error && <p className="text-sm text-terminal-red">{error}</p>}

        {data && (
          <div className="space-y-4 text-sm">
            <section className="rounded border border-terminal-border p-3">
              <p className="mb-2 text-[10px] uppercase text-terminal-muted">Market data</p>
              {data.price_snapshot ? (
                <div className="font-mono">
                  <span className="text-xl font-bold">${data.price_snapshot.price?.toFixed(2)}</span>
                  <span
                    className={`ml-2 ${(data.price_snapshot.pct_change ?? 0) >= 0 ? 'text-terminal-green' : 'text-terminal-red'}`}
                  >
                    {(data.price_snapshot.pct_change ?? 0) >= 0 ? '+' : ''}
                    {data.price_snapshot.pct_change?.toFixed(2)}%
                  </span>
                  {data.price_snapshot.relative_volume != null && (
                    <span className="ml-2 text-terminal-muted">
                      Rel vol {data.price_snapshot.relative_volume}x
                    </span>
                  )}
                  <p className="mt-1 text-[10px] text-terminal-muted">
                    As of {formatTime(data.price_snapshot.snapshot_at)} via {data.price_snapshot.provider}
                  </p>
                </div>
              ) : (
                <p className="text-terminal-muted">No price data</p>
              )}
            </section>

            <section className="rounded border border-terminal-border p-3">
              <p className="mb-2 text-[10px] uppercase text-terminal-muted">Options metrics</p>
              <div className="space-y-1 text-xs text-gray-400">
                <p>Nearest expiry: {data.options_snapshot.nearest_expiry || '—'}</p>
                <p>Avg IV: {data.options_snapshot.avg_iv != null ? String(data.options_snapshot.avg_iv) : '—'}</p>
                <p>
                  P/C vol ratio:{' '}
                  {data.options_snapshot.put_call_volume_ratio != null
                    ? String(data.options_snapshot.put_call_volume_ratio)
                    : '—'}
                </p>
              </div>
            </section>

            {data.social_momentum.mention_count != null && (
              <section className="rounded border border-terminal-border p-3">
                <p className="mb-2 text-[10px] uppercase text-terminal-muted">Social momentum</p>
                <p className="text-xs text-gray-400">
                  Mentions: {data.social_momentum.mention_count}
                  {data.social_momentum.note ? ` · ${data.social_momentum.note}` : ''}
                </p>
              </section>
            )}

            {(data.bull_case || data.bear_case || data.ai_analysis) && (
              <section className="rounded border border-terminal-yellow/30 bg-terminal-panel p-3">
                <p className="mb-2 text-[10px] uppercase text-terminal-yellow">AI interpretation</p>
                {data.ai_analysis && <p className="mb-2 text-xs text-gray-300">{data.ai_analysis}</p>}
                {data.bull_case && (
                  <p className="text-xs text-green-400">
                    <span className="font-semibold">Bull:</span> {data.bull_case}
                  </p>
                )}
                {data.bear_case && (
                  <p className="mt-1 text-xs text-red-400">
                    <span className="font-semibold">Bear:</span> {data.bear_case}
                  </p>
                )}
                <p className="mt-2 text-[10px] text-terminal-muted">
                  Generated {formatTime(data.generated_at)}
                </p>
              </section>
            )}

            {(data.confirmation_levels.length > 0 || data.invalidation_levels.length > 0) && (
              <section className="rounded border border-terminal-border p-3">
                <p className="mb-2 text-[10px] uppercase text-terminal-muted">Levels</p>
                {data.confirmation_levels.length > 0 && (
                  <ul className="mb-2 list-disc pl-4 text-xs text-green-400">
                    {data.confirmation_levels.map((level) => (
                      <li key={level}>{level}</li>
                    ))}
                  </ul>
                )}
                {data.invalidation_levels.length > 0 && (
                  <ul className="list-disc pl-4 text-xs text-red-400">
                    {data.invalidation_levels.map((level) => (
                      <li key={level}>{level}</li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {data.upcoming_events.length > 0 && (
              <section className="rounded border border-terminal-border p-3">
                <p className="mb-2 text-[10px] uppercase text-terminal-muted">Upcoming events</p>
                <ul className="space-y-1 text-xs text-gray-400">
                  {data.upcoming_events.map((event) => (
                    <li key={`${event.event_date}-${event.title}`}>
                      {event.event_date} · {event.title}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {data.recent_catalysts.length > 0 && (
              <section className="rounded border border-terminal-border p-3">
                <p className="mb-2 text-[10px] uppercase text-terminal-muted">Recent catalysts</p>
                <ul className="space-y-2">
                  {data.recent_catalysts.slice(0, 5).map((c) => (
                    <li key={c.id} className="text-xs text-gray-400">
                      <span className="text-terminal-cyan">IMP {c.impact_score}</span> · {c.headline}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {data.data_quality_warnings.length > 0 && (
              <section className="rounded border border-terminal-red/30 p-3 text-xs text-terminal-red">
                {data.data_quality_warnings.map((w) => (
                  <p key={w}>{w}</p>
                ))}
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
