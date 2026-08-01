import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listBriefings } from '../api'
import type { BriefingSummary } from '../types'

export function HistoryPage() {
  const [briefings, setBriefings] = useState<BriefingSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    listBriefings(30, controller.signal)
      .then((data) => {
        setBriefings(data)
        setError(null)
      })
      .catch((err) => {
        if (err instanceof Error && err.name !== 'AbortError') {
          setError(err.message)
        }
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [])

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <p className="animate-pulse text-sm text-research-muted">Loading archive…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-2xl bg-research-red-soft px-4 py-3 text-sm text-research-red">
        {error}
      </div>
    )
  }

  return (
    <div className="animate-fade-up">
      <h1 className="mb-2 text-3xl font-semibold tracking-tight">Archive</h1>
      <p className="mb-8 text-sm text-research-muted">Past daily briefings</p>

      {briefings.length === 0 ? (
        <div className="rounded-2xl bg-research-bg px-6 py-14 text-center text-sm text-research-muted">
          No past briefings yet.
        </div>
      ) : (
        <ul className="rounded-2xl bg-research-surface px-4 shadow-soft sm:px-5">
          {briefings.map((b) => (
            <li key={b.id} className="border-b border-research-line last:border-b-0">
              <Link
                to={`/history/${b.briefing_date}`}
                className="block px-1 py-5 transition hover:bg-research-bg/50"
              >
                <div className="mb-1 flex items-center justify-between gap-3">
                  <span className="font-mono text-sm font-semibold">{b.briefing_date}</span>
                  <span className="text-xs text-research-muted">
                    {b.narrative_count} theme{b.narrative_count === 1 ? '' : 's'}
                  </span>
                </div>
                <p className="line-clamp-2 text-sm leading-6 text-research-muted">{b.summary}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
