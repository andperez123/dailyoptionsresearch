import type { SportsAngle } from '../types'
import { DegenScore } from './DegenScore'

interface SportsStripProps {
  angles: SportsAngle[]
}

export function SportsStrip({ angles }: SportsStripProps) {
  if (angles.length === 0) {
    return (
      <section className="rounded-lg border border-terminal-border bg-terminal-panel p-5">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-terminal-muted">
          Sports Angles
        </h2>
        <p className="text-sm text-gray-500">
          No sports data yet. Add ODDS_API_KEY to .env for live odds, or run research to pull
          sportsbook Reddit chatter.
        </p>
      </section>
    )
  }

  return (
    <section>
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-terminal-muted">
        Sports Angles
      </h2>
      <div className="grid gap-4 md:grid-cols-2">
        {angles.map((angle, i) => (
          <article
            key={i}
            className="rounded-lg border border-terminal-border bg-terminal-panel p-4"
          >
            <div className="mb-2 flex items-start justify-between gap-2">
              <div>
                <span className="text-xs uppercase text-terminal-yellow">{angle.sport}</span>
                <h3 className="font-bold text-white">{angle.title}</h3>
                <p className="text-xs text-terminal-muted">{angle.matchup}</p>
              </div>
              <DegenScore score={angle.degen_score} size="sm" />
            </div>
            <p className="mb-2 text-sm text-gray-300">{angle.narrative}</p>
            {angle.line_note && (
              <p className="mb-1 text-xs text-terminal-cyan">Line: {angle.line_note}</p>
            )}
            {angle.public_vs_sharp && (
              <p className="text-xs text-gray-500">Sharp read: {angle.public_vs_sharp}</p>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}
