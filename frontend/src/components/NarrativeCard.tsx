import { useState } from 'react'
import type { Narrative } from '../types'
import { DegenScore } from './DegenScore'

interface NarrativeCardProps {
  narrative: Narrative
}

export function NarrativeCard({ narrative }: NarrativeCardProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <article className="rounded-lg border border-terminal-border bg-terminal-panel p-5 shadow-lg shadow-black/20">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-bold text-terminal-green">{narrative.title}</h3>
          <div className="mt-1 flex flex-wrap gap-2">
            {narrative.tickers.map((t) => (
              <span
                key={t}
                className="rounded bg-terminal-bg px-2 py-0.5 font-mono text-xs text-terminal-cyan"
              >
                ${t}
              </span>
            ))}
          </div>
        </div>
        <DegenScore score={narrative.degen_score} />
      </div>

      <p className="mb-3 text-sm leading-relaxed text-gray-300">{narrative.story}</p>
      <p className="mb-4 text-xs text-terminal-muted">
        <span className="text-terminal-yellow">WHY NOW:</span> {narrative.why_now}
      </p>

      <div className="mb-4 grid gap-3 md:grid-cols-2">
        <div className="rounded border border-green-900/40 bg-green-950/20 p-3">
          <p className="mb-1 text-xs font-semibold uppercase text-green-400">Bull</p>
          <p className="text-sm text-gray-300">{narrative.bull_case}</p>
        </div>
        <div className="rounded border border-red-900/40 bg-red-950/20 p-3">
          <p className="mb-1 text-xs font-semibold uppercase text-terminal-red">Bear</p>
          <p className="text-sm text-gray-300">{narrative.bear_case}</p>
        </div>
      </div>

      {narrative.catalysts.length > 0 && (
        <div className="mb-4">
          <p className="mb-1 text-xs font-semibold uppercase text-terminal-muted">Catalysts</p>
          <ul className="flex flex-wrap gap-2">
            {narrative.catalysts.map((c) => (
              <li
                key={c}
                className="rounded border border-terminal-border px-2 py-0.5 text-xs text-gray-400"
              >
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}

      {narrative.options_plays.length > 0 && (
        <div className="mb-4">
          <button
            onClick={() => setExpanded(!expanded)}
            className="mb-2 text-xs font-semibold uppercase tracking-wide text-terminal-cyan hover:underline"
          >
            {expanded ? 'Hide' : 'Show'} Options Plays ({narrative.options_plays.length})
          </button>
          {expanded && (
            <div className="space-y-2">
              {narrative.options_plays.map((play, i) => (
                <div
                  key={i}
                  className="rounded border border-terminal-border bg-terminal-bg p-3 text-sm"
                >
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono font-bold text-terminal-yellow">
                      {play.ticker} {play.direction.toUpperCase()}
                    </span>
                    <DegenScore score={play.degen_score} size="sm" />
                  </div>
                  <p className="text-gray-300">
                    {play.strike_zone} · exp {play.expiry}
                  </p>
                  {play.iv_note && (
                    <p className="mt-1 text-xs text-terminal-muted">IV: {play.iv_note}</p>
                  )}
                  {play.risk_note && (
                    <p className="mt-1 text-xs text-terminal-red">Risk: {play.risk_note}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {narrative.sources.length > 0 && (
        <div className="border-t border-terminal-border pt-3">
          <p className="mb-2 text-xs font-semibold uppercase text-terminal-muted">Sources</p>
          <div className="flex flex-wrap gap-2">
            {narrative.sources.map((s, i) => (
              <a
                key={i}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-terminal-cyan hover:underline"
              >
                [{s.source_type}] {s.title.slice(0, 60)}
              </a>
            ))}
          </div>
        </div>
      )}
    </article>
  )
}
