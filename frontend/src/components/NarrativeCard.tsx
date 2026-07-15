import { useState } from 'react'
import type { Narrative } from '../types'
import { DegenScore } from './DegenScore'

interface NarrativeCardProps {
  narrative: Narrative
}

export function NarrativeCard({ narrative }: NarrativeCardProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <article className="rounded-xl border border-terminal-border bg-slate-900/80 p-5 shadow-lg shadow-black/20">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-xl font-bold tracking-tight text-terminal-green">{narrative.title}</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {narrative.tickers.map((t) => (
              <span
                key={t}
                className="rounded-md border border-terminal-cyan/20 bg-terminal-cyan/10 px-2 py-0.5 font-mono text-xs font-semibold text-terminal-cyan"
              >
                ${t}
              </span>
            ))}
          </div>
        </div>
        <DegenScore score={narrative.degen_score} />
      </div>

      <p className="mb-3 max-w-5xl text-[15px] leading-7 text-slate-200">{narrative.story}</p>
      <p className="mb-5 text-sm leading-6 text-terminal-muted">
        <span className="font-mono text-xs font-semibold text-terminal-yellow">WHY NOW:</span>{' '}
        {narrative.why_now}
      </p>

      <div className="mb-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-terminal-green/25 bg-terminal-green/[0.07] p-4">
          <p className="mb-1.5 font-mono text-xs font-semibold uppercase tracking-wide text-terminal-green">Bull</p>
          <p className="text-sm leading-6 text-slate-200">{narrative.bull_case}</p>
        </div>
        <div className="rounded-lg border border-terminal-red/25 bg-terminal-red/[0.07] p-4">
          <p className="mb-1.5 font-mono text-xs font-semibold uppercase tracking-wide text-terminal-red">Bear</p>
          <p className="text-sm leading-6 text-slate-200">{narrative.bear_case}</p>
        </div>
      </div>

      {narrative.catalysts.length > 0 && (
        <div className="mb-4">
          <p className="mb-2 font-mono text-xs font-semibold uppercase tracking-wide text-slate-300">Catalysts</p>
          <ul className="flex flex-wrap gap-2">
            {narrative.catalysts.map((c) => (
              <li
                key={c}
                className="rounded-md border border-terminal-border bg-terminal-bg/60 px-2 py-1 text-xs text-slate-300"
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
        <div className="border-t border-terminal-border pt-4">
          <p className="mb-2 font-mono text-xs font-semibold uppercase tracking-wide text-slate-300">Sources</p>
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
