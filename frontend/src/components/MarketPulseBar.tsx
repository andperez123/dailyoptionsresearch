import { useEffect, useState } from 'react'
import { getPulse } from '../api'
import type { PulseResponse } from '../types'
import { formatTime } from '../lib/format'

export function MarketPulseBar() {
  const [pulse, setPulse] = useState<PulseResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()

    const load = () =>
      getPulse(controller.signal)
        .then((data) => {
          setPulse(data)
          setError(null)
        })
        .catch((err) => {
          if (err instanceof Error && err.name !== 'AbortError') {
            setError(err.message)
          }
        })

    load()
    const id = setInterval(load, 30000)
    return () => {
      controller.abort()
      clearInterval(id)
    }
  }, [])

  const statusLabel: Record<string, string> = {
    open: 'Open',
    pre_market: 'Pre-market',
    closed: 'Closed',
    closed_weekend: 'Weekend',
    unknown: '—',
  }

  const topSector = pulse?.sectors
    ?.filter((s) => s.pct_change != null)
    .sort((a, b) => (b.pct_change ?? 0) - (a.pct_change ?? 0))[0]

  return (
    <div className="border-b border-research-line bg-research-surface">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-5 py-2.5 text-sm">
        <span className="inline-flex items-center gap-1.5 font-medium text-research-ink">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              pulse?.market_status === 'open' ? 'bg-research-green' : 'bg-research-muted'
            }`}
          />
          {statusLabel[pulse?.market_status || 'unknown']}
        </span>

        {error && <span className="text-research-red">Pulse unavailable</span>}

        {pulse?.indices.map((idx) => (
          <div key={idx.symbol} className="flex items-baseline gap-1.5">
            <span className="text-research-muted">{idx.symbol.replace('^', '')}</span>
            <span className="font-mono text-[13px] font-semibold tabular-nums">
              {idx.price?.toFixed(2) ?? '—'}
            </span>
            <span
              className={`font-mono text-[13px] font-semibold tabular-nums ${
                (idx.pct_change ?? 0) >= 0 ? 'text-research-green' : 'text-research-red'
              }`}
            >
              {(idx.pct_change ?? 0) >= 0 ? '+' : ''}
              {idx.pct_change?.toFixed(2) ?? '—'}%
            </span>
          </div>
        ))}

        {topSector && (
          <div className="flex items-baseline gap-1.5 text-research-muted">
            <span>Lead</span>
            <span className="font-medium text-research-ink">{topSector.symbol}</span>
            <span
              className={`font-mono text-[13px] font-semibold tabular-nums ${
                (topSector.pct_change ?? 0) >= 0 ? 'text-research-green' : 'text-research-red'
              }`}
            >
              {(topSector.pct_change ?? 0) >= 0 ? '+' : ''}
              {topSector.pct_change?.toFixed(2)}%
            </span>
          </div>
        )}

        <span className="ml-auto text-xs text-research-muted">
          {pulse ? formatTime(pulse.data_freshness) : '—'}
          {pulse?.provider_warnings?.length ? ' · delayed' : ''}
        </span>
      </div>
    </div>
  )
}
