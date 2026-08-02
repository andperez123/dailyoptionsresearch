import { useState } from 'react'
import type { SportsAngle } from '../types'
import { DegenScore } from './DegenScore'
import { BetDecisionBadge, BetDecisionPanel } from './BetDecisionPanel'

interface SportsStripProps {
  angles: SportsAngle[]
}

export function SportsStrip({ angles }: SportsStripProps) {
  const sorted = [...angles].sort((a, b) => b.degen_score - a.degen_score)
  const [openKey, setOpenKey] = useState<string | null>(null)

  if (sorted.length === 0) {
    return (
      <div className="rounded-2xl bg-research-bg px-6 py-12 text-center text-sm text-research-muted">
        No sports angles in today’s briefing.
      </div>
    )
  }

  return (
    <div className="rounded-2xl bg-research-surface px-4 shadow-soft sm:px-5">
      {sorted.map((angle, i) => {
        const key = `${angle.matchup}-${i}`
        const open = openKey === key
        return (
          <article key={key} className="border-b border-research-line last:border-b-0">
            <button
              type="button"
              onClick={() => setOpenKey(open ? null : key)}
              className="flex w-full items-start justify-between gap-4 px-1 py-4 text-left"
            >
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-research-muted">
                  {angle.sport}
                </p>
                <h3 className="mt-1 text-[15px] font-semibold text-research-ink">{angle.title}</h3>
                <p className="mt-0.5 text-sm text-research-muted">{angle.matchup}</p>
                {angle.bet_decision && (
                  <div className="mt-2">
                    <BetDecisionBadge decision={angle.bet_decision} />
                  </div>
                )}
                {!open && (
                  <p className="mt-2 line-clamp-2 text-sm text-research-muted">{angle.narrative}</p>
                )}
              </div>
              <DegenScore score={angle.degen_score} size="sm" />
            </button>

            {open && (
              <div className="animate-fade-up space-y-3 px-1 pb-5">
                {angle.bet_decision && <BetDecisionPanel decision={angle.bet_decision} />}
                {angle.why_now && (
                  <p className="text-sm text-research-muted">
                    <span className="font-semibold text-research-ink">Why now · </span>
                    {angle.why_now}
                  </p>
                )}
                <p className="text-sm leading-6 text-research-ink">{angle.narrative}</p>
                {angle.line_note && (
                  <p className="text-sm text-research-muted">Line · {angle.line_note}</p>
                )}
                {angle.priced_in && (
                  <p className="text-sm text-research-muted">Priced in · {angle.priced_in}</p>
                )}
                {angle.sources.length > 0 && (
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {angle.sources.map((source, idx) => (
                      <a
                        key={`${source.url}-${idx}`}
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs font-medium text-research-blue hover:underline"
                      >
                        {source.title.slice(0, 60)}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}
