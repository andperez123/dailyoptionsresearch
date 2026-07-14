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

  return (
    <aside className="rounded border border-terminal-border bg-terminal-panel p-3">
      <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-terminal-muted">
        Catalyst Calendar · 7d
      </h3>
      {error ? (
        <p className="text-[10px] text-terminal-red">Calendar unavailable: {error}</p>
      ) : events.length === 0 ? (
        <p className="text-[10px] text-gray-500">No upcoming events for wire tickers.</p>
      ) : (
        <ul className="max-h-48 space-y-2 overflow-y-auto">
          {events.slice(0, 12).map((e) => (
            <li
              key={`${e.event_date}-${e.ticker}-${e.title}`}
              className="rounded border border-terminal-border bg-terminal-bg p-2 text-[10px]"
            >
              <div className="flex justify-between gap-2">
                <span className="font-mono text-terminal-cyan">{e.ticker || '—'}</span>
                <span className="text-terminal-muted">{e.event_date}</span>
              </div>
              <p className="text-gray-400">{e.title}</p>
              <div className="mt-1 flex flex-wrap gap-2 text-terminal-muted">
                {e.iv_level && <span>IV {e.iv_level}</span>}
                {e.vol_context && <span>Vol {e.vol_context}</span>}
                {e.recent_price_change != null && (
                  <span className={e.recent_price_change >= 0 ? 'text-terminal-green' : 'text-terminal-red'}>
                    {e.recent_price_change >= 0 ? '+' : ''}
                    {e.recent_price_change.toFixed(1)}%
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
