import { useState } from 'react'
import type { NarrativeThread, ThreadUpdate } from '../types'

interface ThreadsPanelProps {
  threads: NarrativeThread[]
  onTickerClick?: (ticker: string) => void
}

const updateTypeStyles: Record<string, string> = {
  new: 'bg-research-blue-soft text-research-blue',
  continuing: 'bg-research-bg text-research-muted',
  strengthening: 'bg-research-green-soft text-research-green',
  weakening: 'bg-research-amber-soft text-research-amber',
  resolved: 'bg-research-bg text-research-muted',
  no_new_evidence: 'bg-research-bg text-research-muted',
}

const updateTypeLabels: Record<string, string> = {
  new: 'opened',
  continuing: 'continuing',
  strengthening: 'strengthening',
  weakening: 'weakening',
  resolved: 'resolved',
  no_new_evidence: 'quiet day',
}

const threadStatusStyles: Record<string, string> = {
  active: 'bg-research-green-soft text-research-green',
  stale: 'bg-research-amber-soft text-research-amber',
  closed: 'bg-research-bg text-research-muted',
}

function TimelineEntry({ update }: { update: ThreadUpdate }) {
  return (
    <li className="relative pl-5">
      <span className="absolute left-0 top-[7px] h-2 w-2 rounded-full bg-research-line" />
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs tabular-nums text-research-muted">
          {update.update_date}
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
            updateTypeStyles[update.update_type] ?? updateTypeStyles.continuing
          }`}
        >
          {updateTypeLabels[update.update_type] ?? update.update_type}
        </span>
      </div>
      <p className="mt-1 text-sm leading-6 text-research-ink">{update.note}</p>
    </li>
  )
}

function ThreadCard({
  thread,
  onTickerClick,
}: {
  thread: NarrativeThread
  onTickerClick?: (ticker: string) => void
}) {
  const [open, setOpen] = useState(false)
  const visibleUpdates = open ? thread.updates : thread.updates.slice(0, 3)

  return (
    <article className="rounded-2xl bg-research-surface px-5 py-4 shadow-soft">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => onTickerClick?.(thread.ticker)}
              disabled={!onTickerClick}
              className="font-mono text-sm font-semibold text-research-green hover:underline disabled:cursor-default disabled:no-underline"
            >
              ${thread.ticker}
            </button>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                threadStatusStyles[thread.status] ?? threadStatusStyles.closed
              }`}
            >
              {thread.status}
            </span>
            <span className="rounded-full bg-research-bg px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-research-muted">
              Day {thread.days_tracked}
            </span>
            {thread.direction && (
              <span className="text-[11px] font-medium capitalize text-research-muted">
                {thread.direction}
              </span>
            )}
          </div>
          <h3 className="mt-2 text-base font-semibold tracking-tight text-research-ink">
            {thread.title}
          </h3>
          <p className="mt-1 text-sm leading-6 text-research-muted">{thread.thesis}</p>
        </div>
      </div>

      {thread.updates.length > 0 && (
        <div className="mt-4 border-t border-research-line pt-4">
          <ul className="space-y-3">
            {visibleUpdates.map((update) => (
              <TimelineEntry key={update.id} update={update} />
            ))}
          </ul>
          {thread.updates.length > 3 && (
            <button
              type="button"
              onClick={() => setOpen(!open)}
              className="mt-3 text-xs font-semibold text-research-blue hover:underline"
            >
              {open ? 'Show fewer updates' : `Show all ${thread.updates.length} updates`}
            </button>
          )}
        </div>
      )}
    </article>
  )
}

export function ThreadsPanel({ threads, onTickerClick }: ThreadsPanelProps) {
  if (threads.length === 0) {
    return (
      <div className="rounded-2xl bg-research-bg px-6 py-14 text-center text-sm text-research-muted">
        No narrative threads yet. When a briefing produces a narrative, a running storyline opens
        for each ticker and gets updated every run — even on quiet days.
      </div>
    )
  }

  const active = threads.filter((t) => t.status === 'active')
  const rest = threads.filter((t) => t.status !== 'active')

  return (
    <div className="space-y-6">
      {active.length > 0 && (
        <section className="space-y-4">
          {active.map((thread) => (
            <ThreadCard key={thread.id} thread={thread} onTickerClick={onTickerClick} />
          ))}
        </section>
      )}
      {rest.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-research-muted">Stale · closed</h2>
          <div className="space-y-4">
            {rest.map((thread) => (
              <ThreadCard key={thread.id} thread={thread} onTickerClick={onTickerClick} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
