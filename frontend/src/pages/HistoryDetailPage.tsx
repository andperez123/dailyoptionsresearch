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
        <Link to="/history" className="text-sm text-terminal-cyan hover:underline">
          ← Back to history
        </Link>
        <p className="mt-4 text-terminal-red">{error}</p>
      </div>
    )
  }

  if (!briefing) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <p className="animate-pulse font-mono text-terminal-green">Loading...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Link to="/history" className="text-sm text-terminal-cyan hover:underline">
        ← Back to history
      </Link>
      <div>
        <h1 className="text-2xl font-bold">{briefing.briefing_date}</h1>
        <p className="text-sm text-terminal-muted">
          Generated {new Date(briefing.content.generated_at).toLocaleString()}
        </p>
      </div>

      <section className="rounded-lg border border-terminal-border bg-terminal-panel p-5">
        <p className="text-lg text-gray-200">{briefing.content.summary}</p>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        <div className="space-y-6">
          <section>
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-terminal-muted">
              Narratives
            </h2>
            <div className="space-y-4">
              {briefing.content.narratives.map((n) => (
                <NarrativeCard key={`${n.title}-${n.tickers.join('-')}`} narrative={n} />
              ))}
            </div>
          </section>
          <SportsStrip angles={briefing.content.sports_angles} />
        </div>
        <RadarSidebar items={briefing.content.radar} />
      </div>
    </div>
  )
}
