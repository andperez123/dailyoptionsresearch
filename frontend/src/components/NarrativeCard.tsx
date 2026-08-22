import { useState } from 'react'
import type { Narrative, OptionsPlay } from '../types'
import { DegenScore } from './DegenScore'

interface NarrativeCardProps {
  narrative: Narrative
  threadDay?: number
}

function formatStrategy(play: OptionsPlay): string {
  if (play.strategy_type) {
    return play.strategy_type.replace(/_/g, ' ')
  }
  return play.direction
}

const tierStyles: Record<string, string> = {
  confirmed: 'bg-research-green-soft text-research-green',
  developing: 'bg-research-amber-soft text-research-amber',
  watch: 'bg-research-bg text-research-muted',
}

export function NarrativeCard({ narrative, threadDay }: NarrativeCardProps) {
  const [open, setOpen] = useState(false)
  const quality = narrative.research_quality
  const tier =
    quality?.conviction_tier ??
    (quality?.meets_multi_source_bar ? 'confirmed' : quality?.warning ? 'watch' : undefined)
  const threadStatus = narrative.thread_update?.status

  return (
    <article className="border-b border-research-line last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-start gap-4 px-1 py-5 text-left transition hover:bg-research-bg/60"
      >
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            {narrative.tickers.map((t) => (
              <span
                key={t}
                className="font-mono text-xs font-semibold tracking-wide text-research-green"
              >
                ${t}
              </span>
            ))}
            {quality && tier && (
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                  tierStyles[tier] ?? tierStyles.watch
                }`}
              >
                {tier === 'confirmed'
                  ? `confirmed · ${quality.independent_source_count ?? 0} sources`
                  : tier}
              </span>
            )}
            {(threadDay ?? 0) > 1 && (
              <span className="rounded-full bg-research-blue-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-research-blue">
                Day {threadDay}
                {threadStatus && threadStatus !== 'new' ? ` · ${threadStatus}` : ''}
              </span>
            )}
          </div>
          <h3 className="text-lg font-semibold tracking-tight text-research-ink">{narrative.title}</h3>
          {!open && (
            <p className="mt-1.5 line-clamp-2 text-sm leading-relaxed text-research-muted">
              {narrative.insight || narrative.story}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2 pt-1">
          <DegenScore score={narrative.degen_score} size="sm" />
          <span className="text-xs text-research-muted">{open ? 'Hide' : 'Read'}</span>
        </div>
      </button>

      {open && (
        <div className="animate-fade-up space-y-5 px-1 pb-6">
          <p className="max-w-2xl text-[15px] leading-7 text-research-ink">{narrative.story}</p>

          {narrative.insight && (
            <p className="max-w-2xl text-sm leading-6 text-research-ink">
              <span className="font-semibold">Insight · </span>
              {narrative.insight}
            </p>
          )}

          <p className="max-w-2xl text-sm leading-6 text-research-muted">
            <span className="font-semibold text-research-ink">Why now · </span>
            {narrative.why_now}
          </p>

          {narrative.thread_update?.what_changed && (
            <p className="max-w-2xl text-sm leading-6 text-research-muted">
              <span className="font-semibold text-research-ink">Since last update · </span>
              {narrative.thread_update.what_changed}
            </p>
          )}

          {narrative.priced_in && (
            <p className="max-w-2xl text-sm leading-6 text-research-muted">
              <span className="font-semibold text-research-ink">Priced in · </span>
              {narrative.priced_in}
            </p>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl bg-research-green-soft/70 px-4 py-3">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-research-green">
                Bull case
              </p>
              <p className="text-sm leading-6 text-research-ink">{narrative.bull_case}</p>
            </div>
            <div className="rounded-2xl bg-research-red-soft/70 px-4 py-3">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-research-red">
                Bear case
              </p>
              <p className="text-sm leading-6 text-research-ink">{narrative.bear_case}</p>
            </div>
          </div>

          {((narrative.confirmation_points?.length ?? 0) > 0 ||
            (narrative.invalidation_points?.length ?? 0) > 0) && (
            <div className="grid gap-3 sm:grid-cols-2">
              {(narrative.confirmation_points?.length ?? 0) > 0 && (
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-research-muted">
                    Confirms
                  </p>
                  <ul className="space-y-1 text-sm text-research-ink">
                    {narrative.confirmation_points!.map((point) => (
                      <li key={point}>· {point}</li>
                    ))}
                  </ul>
                </div>
              )}
              {(narrative.invalidation_points?.length ?? 0) > 0 && (
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-research-muted">
                    Invalidates
                  </p>
                  <ul className="space-y-1 text-sm text-research-ink">
                    {narrative.invalidation_points!.map((point) => (
                      <li key={point}>· {point}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {narrative.catalysts.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-research-muted">
                Catalysts
              </p>
              <ul className="flex flex-wrap gap-2">
                {narrative.catalysts.map((c) => (
                  <li
                    key={c}
                    className="rounded-full bg-research-bg px-3 py-1 text-xs font-medium text-research-ink"
                  >
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {narrative.options_plays.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-research-muted">
                Strategy setups
              </p>
              <div className="space-y-3">
                {narrative.options_plays.map((play, i) => (
                  <div key={i} className="rounded-2xl bg-research-bg px-4 py-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="font-mono text-sm font-semibold">
                          {play.ticker}{' '}
                          <span className="capitalize text-research-muted">
                            {formatStrategy(play)}
                          </span>
                        </p>
                        <p className="mt-0.5 text-sm text-research-ink">
                          {play.structure || play.strike_zone}
                          {play.expiry ? ` · ${play.expiry}` : ''}
                        </p>
                        {play.edge && (
                          <p className="mt-1.5 text-sm leading-6 text-research-ink">
                            <span className="font-semibold">Edge · </span>
                            {play.edge}
                          </p>
                        )}
                        {play.thesis && (
                          <p className="mt-1 text-sm leading-6 text-research-muted">{play.thesis}</p>
                        )}
                        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-research-muted">
                          {play.max_loss && <span>Max loss · {play.max_loss}</span>}
                          {play.max_gain && <span>Max gain · {play.max_gain}</span>}
                          {play.breakeven && <span>BE · {play.breakeven}</span>}
                        </div>
                        {play.when_it_wins && (
                          <p className="mt-1 text-xs text-research-green">Wins · {play.when_it_wins}</p>
                        )}
                        {play.when_it_loses && (
                          <p className="mt-0.5 text-xs text-research-red">Loses · {play.when_it_loses}</p>
                        )}
                        {play.iv_note && (
                          <p className="mt-1 text-xs text-research-muted">IV · {play.iv_note}</p>
                        )}
                        {play.risk_note && (
                          <p className="mt-1 text-xs text-research-red">Risk · {play.risk_note}</p>
                        )}
                        {(play.legs?.length ?? 0) > 0 && (
                          <ul className="mt-2 space-y-0.5 font-mono text-[11px] text-research-muted">
                            {play.legs!.map((leg, li) => (
                              <li key={li}>
                                {leg.action.toUpperCase()} {leg.quantity ?? 1}x {leg.strike}
                                {leg.option_type?.[0]?.toUpperCase()} {leg.expiry}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                      <DegenScore score={play.degen_score} size="sm" />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {narrative.sources.length > 0 && (
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {narrative.sources.map((s, i) => (
                <a
                  key={i}
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs font-medium text-research-blue hover:underline"
                >
                  [{s.source_type}] {s.title.slice(0, 48)}
                  {s.title.length > 48 ? '…' : ''}
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </article>
  )
}
