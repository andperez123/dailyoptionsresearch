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
  const [minConfidence, setMinConfidence] = useState(5)
  const [direction, setDirection] = useState('')
  const requestId = useRef(0)

  const load = useCallback(async (signal?: AbortSignal) => {
    const currentRequest = ++requestId.current
    setLoading(true)
    try {
      const data = await getWire(
        {
          page: 1,
          page_size: 40,
          min_impact: minImpact,
          min_confidence: minConfidence,
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
      if (err instanceof Error && err.name !== 'AbortError' && currentRequest === requestId.current) {
        setError(err.message)
      }
    } finally {
      if (currentRequest === requestId.current) {
        setLoading(false)
      }
    }
  }, [minImpact, minConfidence, direction])

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
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-terminal-muted">
            Live Catalyst Wire
          </h2>
          <p className="text-[10px] text-terminal-muted">
            Signals ranked by impact + confidence · showing {items.length} of {total}
          </p>
        </div>
        <button
          onClick={handleScan}
          disabled={scanning}
          className="rounded border border-terminal-cyan/50 px-2 py-1 text-[10px] text-terminal-cyan hover:bg-terminal-cyan/10 disabled:opacity-50"
        >
          {scanning ? 'Scanning...' : 'Scan now'}
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded border border-terminal-red/40 p-2 text-xs text-terminal-red">
          {error}
          <button onClick={() => load()} className="ml-2 underline">
            Retry
          </button>
        </div>
      )}

      <div className="mb-3 flex flex-wrap gap-3 text-[10px]">
        <label className="flex items-center gap-1 text-terminal-muted">
          Min impact
          <input
            type="range"
            min={0}
            max={10}
            value={minImpact}
            onChange={(e) => setMinImpact(Number(e.target.value))}
            className="w-20"
          />
          {minImpact}
        </label>
        <label className="flex items-center gap-1 text-terminal-muted">
          Min confidence
          <input
            type="range"
            min={0}
            max={10}
            value={minConfidence}
            onChange={(e) => setMinConfidence(Number(e.target.value))}
            className="w-20"
          />
          {minConfidence}
        </label>
        <select
          value={direction}
          onChange={(e) => setDirection(e.target.value)}
          className="rounded border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-muted"
        >
          <option value="">All directions</option>
          <option value="bullish">Bullish</option>
          <option value="bearish">Bearish</option>
          <option value="volatility">Volatility</option>
          <option value="mixed">Mixed</option>
        </select>
      </div>

      {loading ? (
        <p className="animate-pulse text-xs text-terminal-green">Loading wire...</p>
      ) : items.length === 0 ? (
        <div className="rounded border border-dashed border-terminal-border p-6 text-center text-xs text-terminal-muted">
          No catalyst signals yet. Start the worker with <code className="text-terminal-cyan">make worker</code>{' '}
          or hit Scan now.
        </div>
      ) : (
        <div className="space-y-2">
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
