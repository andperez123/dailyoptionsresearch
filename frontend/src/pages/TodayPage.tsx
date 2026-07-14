import { useCallback, useEffect, useState } from 'react'
import { getLatestBriefing, getStatus, getWire, runResearch } from '../api'
import { CatalystCalendarStrip } from '../components/CatalystCalendarStrip'
import { CatalystWire } from '../components/CatalystWire'
import { DeepDiveDrawer } from '../components/DeepDiveDrawer'
import { NarrativeCard } from '../components/NarrativeCard'
import { RadarSidebar } from '../components/RadarSidebar'
import { SportsStrip } from '../components/SportsStrip'
import type { BriefingRecord, ResearchStatus, ScoredCatalyst } from '../types'

export function TodayPage() {
  const [briefing, setBriefing] = useState<BriefingRecord | null>(null)
  const [status, setStatus] = useState<ResearchStatus | null>(null)
  const [alerts, setAlerts] = useState<ScoredCatalyst[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)
  const [showNarratives, setShowNarratives] = useState(true)

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [b, s, wire] = await Promise.all([
        getLatestBriefing(signal),
        getStatus(signal),
        getWire({ page: 1, page_size: 8, min_impact: 8, min_confidence: 5 }, signal),
      ])
      setBriefing(b)
      setStatus(s)
      setAlerts(wire.items)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load terminal data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)

    const interval = setInterval(() => {
      getStatus()
        .then(setStatus)
        .catch(() => {})
    }, 10000)

    return () => {
      controller.abort()
      clearInterval(interval)
    }
  }, [load])

  const handleRunResearch = async () => {
    try {
      await runResearch()
      window.setTimeout(() => load(), 5000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start briefing')
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <p className="animate-pulse font-mono text-terminal-green">Loading terminal...</p>
      </div>
    )
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-white">Catalyst Terminal</h1>
          <p className="text-[10px] text-terminal-muted">
            Narratives = themes · Catalysts = what happened · Setups = investigate further
          </p>
        </div>
        <button
          onClick={handleRunResearch}
          disabled={status?.running}
          className="rounded border border-terminal-green/50 px-3 py-1 text-xs text-terminal-green hover:bg-terminal-green/10 disabled:opacity-50"
        >
          {status?.running ? 'Briefing running...' : 'Run daily briefing'}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded border border-terminal-red/40 bg-terminal-panel p-3 text-xs text-terminal-red">
          {error}
          <button onClick={() => load()} className="ml-3 underline">
            Retry
          </button>
        </div>
      )}

      {status?.last_error && (
        <div className="mb-4 rounded border border-terminal-yellow/40 bg-terminal-panel p-3 text-xs text-terminal-yellow">
          Pipeline error: {status.last_error}
        </div>
      )}

      {briefing && (
        <section className="mb-4 rounded border border-terminal-border bg-terminal-panel p-3">
          <button
            onClick={() => setShowNarratives(!showNarratives)}
            className="mb-2 text-[10px] uppercase text-terminal-muted hover:text-terminal-green"
          >
            {showNarratives ? 'Collapse' : 'Expand'} daily narrative · {briefing.briefing_date}
          </button>
          {showNarratives && (
            <>
              <p className="text-sm leading-relaxed text-gray-300">{briefing.content.summary}</p>
              {briefing.content.narratives.length > 0 && (
                <div className="mt-3 space-y-2">
                  {briefing.content.narratives.slice(0, 2).map((n) => (
                    <NarrativeCard key={`${n.title}-${n.tickers.join('-')}`} narrative={n} />
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      )}

      {!briefing && !error && (
        <div className="mb-4 rounded border border-dashed border-terminal-border p-4 text-center text-xs text-terminal-muted">
          No daily briefing yet. Run the worker or click &quot;Run daily briefing&quot;.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
        <div className="space-y-4">
          <CatalystWire onTickerClick={setSelectedTicker} />
          {briefing && <SportsStrip angles={briefing.content.sports_angles} />}
        </div>

        <div className="space-y-3">
          {briefing && <RadarSidebar items={briefing.content.radar} />}
          <CatalystCalendarStrip />
          <aside className="rounded border border-terminal-border bg-terminal-panel p-3">
            <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-terminal-muted">
              High-Impact Alerts
            </h3>
            {alerts.length === 0 ? (
              <p className="text-[10px] text-gray-500">No signals with impact ≥ 8 yet.</p>
            ) : (
              <ul className="space-y-2">
                {alerts.map((alert) => (
                  <li key={alert.id} className="text-[10px] text-gray-400">
                    <button
                      onClick={() => alert.primary_ticker && setSelectedTicker(alert.primary_ticker)}
                      className="text-left hover:text-terminal-green"
                    >
                      <span className="text-terminal-cyan">IMP {alert.impact_score}</span> · {alert.headline}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>
        </div>
      </div>

      <DeepDiveDrawer ticker={selectedTicker} onClose={() => setSelectedTicker(null)} />
    </>
  )
}
