import { useEffect, useState } from 'react'
import { getCalendar } from '../api'
import type { CalendarEvent } from '../types'

export function CatalystCalendarStrip() {
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getCalendar(7, true, controller.signal)
      .then((data) => {
        setEvents(data)
        setError(null)
      })
      .catch((err) => {
        if (err instanceof Error && err.name !== 'AbortError') {
          setError(err.message)
        }
      })
    return () => controller.abort()
  }, [])

  if (error) {
    return <p className="py-8 text-center text-sm text-research-red">Calendar unavailable</p>
  }

  if (events.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-research-muted">
        No upcoming events for watched tickers.
      </p>
    )
  }

  return (
    <ul>
      {events.slice(0, 12).map((e) => (
        <li
          key={`${e.event_date}-${e.ticker}-${e.title}`}
          className="flex items-start justify-between gap-4 border-b border-research-line px-1 py-4 last:border-b-0"
        >
          <div>
            <p className="font-mono text-sm font-semibold text-research-green">
              {e.ticker ? `$${e.ticker}` : 'Market'}
            </p>
            <p className="mt-1 text-sm text-research-ink">{e.title}</p>
            <div className="mt-1.5 flex flex-wrap gap-2 text-xs text-research-muted">
              {e.iv_level && <span>IV {e.iv_level}</span>}
              {e.vol_context && <span>Vol {e.vol_context}</span>}
              {e.recent_price_change != null && (
                <span
                  className={
                    e.recent_price_change >= 0 ? 'text-research-green' : 'text-research-red'
                  }
                >
                  {e.recent_price_change >= 0 ? '+' : ''}
                  {e.recent_price_change.toFixed(1)}%
                </span>
              )}
            </div>
          </div>
          <span className="shrink-0 font-mono text-xs text-research-muted">{e.event_date}</span>
        </li>
      ))}
    </ul>
  )
}
