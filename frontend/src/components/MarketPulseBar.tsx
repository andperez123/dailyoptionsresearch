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
    open: 'MARKET OPEN',
    pre_market: 'PRE-MARKET',
    closed: 'CLOSED',
    closed_weekend: 'WEEKEND',
    unknown: 'UNKNOWN',
  }

  const topSector = pulse?.sectors
    ?.filter((s) => s.pct_change != null)
    .sort((a, b) => (b.pct_change ?? 0) - (a.pct_change ?? 0))[0]

  return (
    <div className="border-b border-terminal-border bg-terminal-panel/80 px-4 py-2">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-4 text-xs">
        <span className="font-semibold text-terminal-green">
          {statusLabel[pulse?.market_status || 'unknown']}
        </span>
        {error && <span className="text-terminal-red">Pulse unavailable</span>}
        {pulse?.indices.map((idx) => (
          <div key={idx.symbol} className="flex items-center gap-1.5">
            <span className="text-terminal-muted">{idx.symbol.replace('^', '')}</span>
            <span className="font-bold text-white">{idx.price?.toFixed(2) ?? '—'}</span>
            <span
              className={
                (idx.pct_change ?? 0) >= 0 ? 'text-terminal-green' : 'text-terminal-red'
              }
            >
              {(idx.pct_change ?? 0) >= 0 ? '+' : ''}
              {idx.pct_change?.toFixed(2) ?? '—'}%
            </span>
          </div>
        ))}
        {topSector && (
          <div className="text-terminal-muted">
            Top sector <span className="text-terminal-cyan">{topSector.symbol}</span>{' '}
            <span
              className={
                (topSector.pct_change ?? 0) >= 0 ? 'text-terminal-green' : 'text-terminal-red'
              }
            >
              {(topSector.pct_change ?? 0) >= 0 ? '+' : ''}
              {topSector.pct_change?.toFixed(2)}%
            </span>
          </div>
        )}
        <span className="ml-auto text-[10px] text-terminal-muted">
          Updated {pulse ? formatTime(pulse.data_freshness) : '—'}
          {pulse?.provider_warnings?.length ? ' · delayed data' : ''}
        </span>
      </div>
    </div>
  )
}
