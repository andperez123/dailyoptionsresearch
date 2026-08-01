import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getBriefingByDate } from '../api'
import type { BriefingRecord } from '../types'
import { NarrativeCard } from '../components/NarrativeCard'
import { RadarSidebar } from '../components/RadarSidebar'
import { SportsStrip } from '../components/SportsStrip'

export function HistoryDetailPage() {
  const { date } = useParams<{ date: string }>()
  const [briefing, setBriefing] = useState<BriefingRecord | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!date) return
    const controller = new AbortController()
    getBriefingByDate(date, controller.signal)
      .then(setBriefing)
      .catch((e) => {
        if (e instanceof Error && e.name !== 'AbortError') {
          setError(e.message)
        }
      })
    return () => controller.abort()
  }, [date])

  if (error) {
    return (
      <div>
        <Link to="/history" className="text-sm font-medium text-research-blue hover:underline">
          ← Archive
        </Link>
        <p className="mt-4 text-research-red">{error}</p>
      </div>
    )
  }

  if (!briefing) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <p className="animate-pulse text-sm text-research-muted">Loading…</p>
      </div>
    )
  }

  return (
    <div className="animate-fade-up space-y-8">
      <div>
        <Link to="/history" className="text-sm font-medium text-research-blue hover:underline">
          ← Archive
        </Link>
        <h1 className="mt-3 font-mono text-3xl font-semibold tracking-tight">
          {briefing.briefing_date}
        </h1>
        <p className="mt-1 text-sm text-research-muted">
          Generated {new Date(briefing.content.generated_at).toLocaleString()}
        </p>
        <p className="mt-4 max-w-2xl text-base leading-7 text-research-muted">
          {briefing.content.summary}
        </p>
      </div>

      <section className="rounded-2xl bg-research-surface px-4 shadow-soft sm:px-5">
        {briefing.content.narratives.map((n) => (
          <NarrativeCard key={`${n.title}-${n.tickers.join('-')}`} narrative={n} />
        ))}
      </section>

      {briefing.content.sports_angles.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-research-muted">Sports angles</h2>
          <SportsStrip angles={briefing.content.sports_angles} />
        </section>
      )}

      {briefing.content.radar.length > 0 && (
        <section className="rounded-2xl bg-research-surface px-4 shadow-soft sm:px-5">
          <h2 className="border-b border-research-line px-1 py-4 text-sm font-semibold">Buzz</h2>
          <RadarSidebar items={briefing.content.radar} />
        </section>
      )}
    </div>
  )
}
