import { useCallback, useEffect, useState } from 'react'
import {
  getLatestBriefing,
  getLatestRunReport,
  getStatus,
  getThreads,
  getWire,
  runResearch,
} from '../api'
import { CatalystCalendarStrip } from '../components/CatalystCalendarStrip'
import { CatalystWire } from '../components/CatalystWire'
import { DeepDiveDrawer } from '../components/DeepDiveDrawer'
import { NarrativeCard } from '../components/NarrativeCard'
import { RadarSidebar } from '../components/RadarSidebar'
import { RunReportPanel } from '../components/RunReportPanel'
import { SportsStrip } from '../components/SportsStrip'
import { ThreadsPanel } from '../components/ThreadsPanel'
import type {
  BriefingRecord,
  NarrativeThread,
  ResearchStatus,
  RunReportRecord,
  ScoredCatalyst,
} from '../types'

type Tab = 'themes' | 'threads' | 'signals' | 'watch' | 'analysis'

const tabs: { id: Tab; label: string }[] = [
  { id: 'themes', label: 'Themes' },
  { id: 'threads', label: 'Threads' },
  { id: 'signals', label: 'Signals' },
  { id: 'watch', label: 'Watch' },
  { id: 'analysis', label: 'Analysis' },
]

export function TodayPage() {
  const [briefing, setBriefing] = useState<BriefingRecord | null>(null)
  const [status, setStatus] = useState<ResearchStatus | null>(null)
  const [alerts, setAlerts] = useState<ScoredCatalyst[]>([])
  const [runReport, setRunReport] = useState<RunReportRecord | null>(null)
  const [threads, setThreads] = useState<NarrativeThread[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('themes')

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [b, s, wire, report, threadList] = await Promise.all([
        getLatestBriefing(signal),
        getStatus(signal),
        getWire({ page: 1, page_size: 6, min_impact: 8, min_confidence: 5 }, signal),
        getLatestRunReport(signal).catch(() => null),
        getThreads(undefined, signal).catch(() => [] as NarrativeThread[]),
      ])
      setBriefing(b)
      setStatus(s)
      setAlerts(wire.items)
      setRunReport(report)
      setThreads(threadList)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load research')
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
        <p className="animate-pulse text-sm text-research-muted">Loading today’s research…</p>
      </div>
    )
  }

  return (
    <>
      <div className="mb-8 animate-fade-up">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-research-muted">
              {briefing?.briefing_date || 'No briefing yet'}
            </p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight text-research-ink">
              Today
            </h1>
          </div>
          <button
            type="button"
            onClick={handleRunResearch}
            disabled={status?.running}
            className="rounded-full bg-research-green px-4 py-2 text-sm font-semibold text-white transition hover:bg-research-green/90 disabled:opacity-50"
          >
            {status?.running ? 'Running…' : 'Refresh briefing'}
          </button>
        </div>

        {briefing?.content.summary && (
          <p className="mt-4 max-w-2xl text-base leading-7 text-research-muted">
            {briefing.content.summary}
          </p>
        )}
      </div>

      {error && (
        <div className="mb-5 rounded-2xl bg-research-red-soft px-4 py-3 text-sm text-research-red">
          {error}
          <button type="button" onClick={() => load()} className="ml-2 font-semibold underline">
            Retry
          </button>
        </div>
      )}

      {status?.last_error && (
        <div className="mb-5 rounded-2xl bg-research-amber-soft px-4 py-3 text-sm text-research-amber">
          Pipeline · {status.last_error}
        </div>
      )}

      <div className="mb-6 flex gap-1 rounded-full bg-research-bg p-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`flex-1 rounded-full px-4 py-2 text-sm font-semibold transition ${
              tab === t.id
                ? 'bg-research-surface text-research-ink shadow-soft'
                : 'text-research-muted hover:text-research-ink'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'themes' && (
        <div className="animate-fade-up space-y-6">
          {!briefing ? (
            <div className="rounded-2xl bg-research-bg px-6 py-14 text-center text-sm text-research-muted">
              No daily briefing yet. Hit refresh to generate one.
            </div>
          ) : (
            <>
              <section className="rounded-2xl bg-research-surface px-4 shadow-soft sm:px-5">
                {briefing.content.narratives.length === 0 ? (
                  <div className="px-2 py-10 text-center">
                    <p className="text-sm text-research-muted">
                      No themes in this briefing.
                    </p>
                    {runReport && (
                      <>
                        <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-research-ink">
                          {runReport.headline}
                        </p>
                        <button
                          type="button"
                          onClick={() => setTab('analysis')}
                          className="mt-3 text-sm font-semibold text-research-blue hover:underline"
                        >
                          See what the analysis produced →
                        </button>
                      </>
                    )}
                  </div>
                ) : (
                  briefing.content.narratives.map((n) => (
                    <NarrativeCard
                      key={`${n.title}-${n.tickers.join('-')}`}
                      narrative={n}
                      threadDay={Math.max(
                        0,
                        ...threads
                          .filter((t) => n.tickers.includes(t.ticker))
                          .map((t) => t.days_tracked),
                      )}
                    />
                  ))
                )}
              </section>

              {briefing.content.sports_angles.length > 0 && (
                <section>
                  <h2 className="mb-3 text-sm font-semibold text-research-muted">Sports angles</h2>
                  <SportsStrip angles={briefing.content.sports_angles} />
                </section>
              )}
            </>
          )}
        </div>
      )}

      {tab === 'threads' && (
        <div className="animate-fade-up">
          <ThreadsPanel threads={threads} onTickerClick={setSelectedTicker} />
        </div>
      )}

      {tab === 'analysis' && (
        <div className="animate-fade-up">
          <RunReportPanel report={runReport} onTickerClick={setSelectedTicker} />
        </div>
      )}

      {tab === 'signals' && (
        <div className="animate-fade-up">
          <CatalystWire onTickerClick={setSelectedTicker} />
        </div>
      )}

      {tab === 'watch' && (
        <div className="animate-fade-up grid gap-6 lg:grid-cols-2">
          <section className="rounded-2xl bg-research-surface px-4 shadow-soft sm:px-5">
            <h2 className="border-b border-research-line px-1 py-4 text-sm font-semibold text-research-ink">
              Buzz
            </h2>
            <RadarSidebar
              items={briefing?.content.radar ?? []}
              onTickerClick={setSelectedTicker}
            />
          </section>

          <section className="rounded-2xl bg-research-surface px-4 shadow-soft sm:px-5">
            <h2 className="border-b border-research-line px-1 py-4 text-sm font-semibold text-research-ink">
              Calendar · 7 days
            </h2>
            <CatalystCalendarStrip />
          </section>

          <section className="rounded-2xl bg-research-surface px-4 shadow-soft sm:px-5 lg:col-span-2">
            <h2 className="border-b border-research-line px-1 py-4 text-sm font-semibold text-research-ink">
              High impact
            </h2>
            {alerts.length === 0 ? (
              <p className="py-8 text-center text-sm text-research-muted">
                No signals with impact ≥ 8 yet.
              </p>
            ) : (
              <ul>
                {alerts.map((alert) => (
                  <li key={alert.id} className="border-b border-research-line last:border-b-0">
                    <button
                      type="button"
                      onClick={() =>
                        alert.primary_ticker && setSelectedTicker(alert.primary_ticker)
                      }
                      className="flex w-full items-start gap-3 px-1 py-4 text-left transition hover:bg-research-bg/50"
                    >
                      <span className="mt-0.5 font-mono text-sm font-semibold tabular-nums text-research-green">
                        {alert.impact_score}
                      </span>
                      <span className="text-sm leading-6 text-research-ink">{alert.headline}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}

      <DeepDiveDrawer ticker={selectedTicker} onClose={() => setSelectedTicker(null)} />
    </>
  )
}
