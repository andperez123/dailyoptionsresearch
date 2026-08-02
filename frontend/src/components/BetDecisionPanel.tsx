import { useState } from 'react'
import type { SportsBetDecision } from '../types'

const DECISION_STYLES: Record<string, { badge: string; label: string }> = {
  bet: { badge: 'bg-research-green-soft text-research-green', label: 'BET' },
  lean: { badge: 'bg-research-amber-soft text-research-amber', label: 'LEAN' },
  pass: { badge: 'bg-research-bg text-research-muted', label: 'PASS' },
}

function formatPrice(price: number): string {
  return price > 0 ? `+${price}` : `${price}`
}

export function pickLabel(d: SportsBetDecision): string {
  const point =
    d.point != null ? (d.market === 'spreads' && d.point > 0 ? ` +${d.point}` : ` ${d.point}`) : ''
  return `${d.selection}${point} ${d.market_label} ${formatPrice(d.best_price)}`
}

export function BetDecisionBadge({ decision }: { decision: SportsBetDecision }) {
  const style = DECISION_STYLES[decision.decision] ?? DECISION_STYLES.pass
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${style.badge}`}
    >
      {style.label}
      {decision.decision !== 'pass' && (
        <span className="font-mono tabular-nums">{pickLabel(decision)}</span>
      )}
    </span>
  )
}

export function BetDecisionPanel({ decision }: { decision: SportsBetDecision }) {
  const [showChecklist, setShowChecklist] = useState(false)
  const style = DECISION_STYLES[decision.decision] ?? DECISION_STYLES.pass

  return (
    <div className="rounded-2xl border border-research-line bg-research-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide ${style.badge}`}
          >
            {style.label}
          </span>
          <span className="font-mono text-sm font-semibold tabular-nums text-research-ink">
            {pickLabel(decision)}
          </span>
          <span className="text-xs text-research-muted">@ {decision.best_bookmaker}</span>
        </div>
        {decision.stake_units > 0 && (
          <span className="font-mono text-xs font-semibold tabular-nums text-research-ink">
            {decision.stake_units}u
          </span>
        )}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-research-muted">Edge</p>
          <p
            className={`font-mono text-sm font-semibold tabular-nums ${
              decision.edge_pct > 0 ? 'text-research-green' : 'text-research-red'
            }`}
          >
            {decision.edge_pct > 0 ? '+' : ''}
            {decision.edge_pct.toFixed(1)} pts
          </p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wide text-research-muted">EV / unit</p>
          <p
            className={`font-mono text-sm font-semibold tabular-nums ${
              decision.ev_pct > 0 ? 'text-research-green' : 'text-research-red'
            }`}
          >
            {decision.ev_pct > 0 ? '+' : ''}
            {decision.ev_pct.toFixed(1)}%
          </p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wide text-research-muted">Fair prob</p>
          <p className="font-mono text-sm tabular-nums text-research-ink">
            {(decision.consensus_probability * 100).toFixed(1)}%
          </p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wide text-research-muted">Confidence</p>
          <p className="font-mono text-sm tabular-nums text-research-ink">
            {decision.confidence.toFixed(1)}/10
          </p>
        </div>
      </div>

      <p className="mt-3 text-sm leading-6 text-research-ink">{decision.rationale}</p>

      {decision.key_factors.length > 0 && (
        <ul className="mt-2 space-y-1">
          {decision.key_factors.map((factor) => (
            <li key={factor} className="text-sm text-research-muted">
              · {factor}
            </li>
          ))}
        </ul>
      )}

      {decision.risks.length > 0 && (
        <p className="mt-2 text-xs text-research-red">
          Risk · {decision.risks[0]}
        </p>
      )}

      {decision.research_checklist.length > 0 && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowChecklist(!showChecklist)}
            className="text-xs font-semibold text-research-blue hover:underline"
          >
            {showChecklist ? 'Hide' : 'Show'} pre-bet research checklist (
            {decision.research_checklist.length})
          </button>
          {showChecklist && (
            <ul className="mt-2 space-y-1.5 rounded-2xl bg-research-bg px-4 py-3">
              {decision.research_checklist.map((item) => (
                <li key={item} className="text-sm text-research-ink">
                  ☐ {item}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
