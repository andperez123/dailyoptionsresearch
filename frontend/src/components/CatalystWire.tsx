import { useCallback, useEffect, useRef, useState } from 'react'
import { getWire, postCatalystFeedback, runCatalystScan } from '../api'
import type { ScoredCatalyst } from '../types'
import { CatalystCard } from './CatalystCard'

interface CatalystWireProps {
  onTickerClick: (ticker: string) => void
}

export function CatalystWire({ onTickerClick }: CatalystWireProps) {
  const [items, setItems] = useState<ScoredCatalyst[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [feedbackState, setFeedbackState] = useState<Record<number, string>>({})
  const [minImpact, setMinImpact] = useState(5)
  const [direction, setDirection] = useState('')
  const requestId = useRef(0)

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const currentRequest = ++requestId.current
      setLoading(true)
      try {
        const data = await getWire(
          {
            page: 1,
            page_size: 40,
            min_impact: minImpact,
            min_confidence: 5,
            ...(direction ? { direction } : {}),
          },
          signal,
        )
        if (currentRequest === requestId.current) {
          setItems(data.items)
          setTotal(data.total)
          setError(null)
        }
      } catch (err) {
        if (
          err instanceof Error &&
          err.name !== 'AbortError' &&
          currentRequest === requestId.current
        ) {
          setError(err.message)
        }
      } finally {
        if (currentRequest === requestId.current) {
          setLoading(false)
        }
      }
    },
    [minImpact, direction],
  )

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    const id = setInterval(() => load(), 60000)
    return () => {
      controller.abort()
      clearInterval(id)
    }
  }, [load])

  const handleScan = async () => {
    setScanning(true)
    try {
      await runCatalystScan()
      window.setTimeout(() => load(), 3000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const handleFeedback = async (id: number, label: string) => {
    try {
      await postCatalystFeedback(id, label)
      setFeedbackState((prev) => ({ ...prev, [id]: label }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Feedback failed')
    }
  }

  return (
    <section>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-research-muted">
          {loading ? 'Loading…' : `${items.length} of ${total} signals`}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={String(minImpact)}
            onChange={(e) => setMinImpact(Number(e.target.value))}
            className="rounded-full border border-research-line bg-research-surface px-3 py-1.5 text-xs font-medium text-research-ink"
          >
            <option value={0}>All impact</option>
            <option value={5}>Impact ≥ 5</option>
            <option value={7}>Impact ≥ 7</option>
            <option value={8}>Impact ≥ 8</option>
          </select>
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
            className="rounded-full border border-research-line bg-research-surface px-3 py-1.5 text-xs font-medium text-research-ink"
          >
            <option value="">All directions</option>
            <option value="bullish">Bullish</option>
            <option value="bearish">Bearish</option>
            <option value="volatility">Volatility</option>
            <option value="mixed">Mixed</option>
          </select>
          <button
            type="button"
            onClick={handleScan}
            disabled={scanning}
            className="rounded-full bg-research-ink px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-research-ink/90 disabled:opacity-50"
          >
            {scanning ? 'Scanning…' : 'Scan'}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-2xl bg-research-red-soft px-4 py-3 text-sm text-research-red">
          {error}
          <button type="button" onClick={() => load()} className="ml-2 font-semibold underline">
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <p className="animate-pulse py-12 text-center text-sm text-research-muted">
          Loading signals…
        </p>
      ) : items.length === 0 ? (
        <div className="rounded-2xl bg-research-bg px-6 py-12 text-center text-sm text-research-muted">
          No signals yet. Run a scan to pull fresh catalysts.
        </div>
      ) : (
        <div className="rounded-2xl bg-research-surface px-4 shadow-soft sm:px-5">
          {items.map((c) => (
            <CatalystCard
              key={c.id}
              catalyst={c}
              onTickerClick={onTickerClick}
              onFeedback={handleFeedback}
              feedbackLabel={feedbackState[c.id]}
            />
          ))}
        </div>
      )}
    </section>
  )
}
