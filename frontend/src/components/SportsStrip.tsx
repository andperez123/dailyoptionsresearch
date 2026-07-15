import type { SportsAngle } from '../types'
import { DegenScore } from './DegenScore'

interface SportsStripProps {
  angles: SportsAngle[]
}

export function SportsStrip({ angles }: SportsStripProps) {
  const sorted = [...angles].sort((a, b) => b.degen_score - a.degen_score)

  if (sorted.length === 0) {
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
        {sorted.map((angle, i) => (
          <article
            key={`${angle.matchup}-${i}`}
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
            {angle.why_now && (
              <p className="mb-2 text-xs text-terminal-yellow">Why now: {angle.why_now}</p>
            )}
            <p className="mb-2 text-sm text-gray-300">{angle.narrative}</p>
            {angle.line_note && (
              <p className="mb-1 text-xs text-terminal-cyan">Line: {angle.line_note}</p>
            )}
            {angle.priced_in && (
              <p className="mb-1 text-xs text-gray-500">Priced in: {angle.priced_in}</p>
            )}
            {angle.sources.length > 0 && (
              <div className="mt-3 border-t border-terminal-border pt-2">
                <p className="mb-1 text-[10px] uppercase text-terminal-muted">Sources</p>
                <div className="flex flex-col gap-1">
                  {angle.sources.map((source, idx) => (
                    <a
                      key={`${source.url}-${idx}`}
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-terminal-cyan hover:underline"
                    >
                      [{source.source_type}] {source.title.slice(0, 80)}
                    </a>
                  ))}
                </div>
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}
