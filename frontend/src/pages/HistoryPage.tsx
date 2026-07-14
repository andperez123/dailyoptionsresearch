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
        <p className="animate-pulse font-mono text-terminal-green">Loading history...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded border border-terminal-red/40 p-4 text-sm text-terminal-red">
        {error}
      </div>
    )
  }

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold">Briefing History</h1>
      {briefings.length === 0 ? (
        <p className="text-terminal-muted">No past briefings yet.</p>
      ) : (
        <ul className="space-y-3">
          {briefings.map((b) => (
            <li key={b.id}>
              <Link
                to={`/history/${b.briefing_date}`}
                className="block rounded-lg border border-terminal-border bg-terminal-panel p-4 transition hover:border-terminal-green/50"
              >
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-mono font-bold text-terminal-cyan">{b.briefing_date}</span>
                  <span className="text-xs text-terminal-muted">{b.narrative_count} narratives</span>
                </div>
                <p className="line-clamp-2 text-sm text-gray-400">{b.summary}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
