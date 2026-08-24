import type { DossierVerdict, RunReportRecord, RunStage } from '../types'

interface RunReportPanelProps {
  report: RunReportRecord | null
  onTickerClick?: (ticker: string) => void
}

const statusStyles: Record<string, string> = {
  success: 'bg-research-green-soft text-research-green',
  empty: 'bg-research-amber-soft text-research-amber',
  failed: 'bg-research-red-soft text-research-red',
  running: 'bg-research-bg text-research-muted',
}

const stageLabels: Record<string, string> = {
  reddit_collected: 'Reddit collected',
  ticker_buzz: 'Ticker buzz',
  watchlist: 'Watchlist',
  sports: 'Sports data',
  market_data: 'Market data',
  overnight_catalysts: 'Overnight catalysts',
  dossiers: 'Dossiers built',
  synthesis: 'LLM synthesis',
  threads: 'Narrative threads',
}

function stageSummary(stage: RunStage): string {
  const parts: string[] = []
  for (const [key, value] of Object.entries(stage)) {
    if (key === 'stage' || key === 'at') continue
    if (Array.isArray(value)) {
      if (value.length > 0 && typeof value[0] === 'string') {
        parts.push(`${key.replace(/_/g, ' ')}: ${(value as string[]).slice(0, 8).join(', ')}`)
      } else if (value.length > 0) {
        parts.push(`${key.replace(/_/g, ' ')}: ${value.length}`)
      }
    } else if (typeof value === 'number' || typeof value === 'boolean') {
      parts.push(`${key.replace(/_/g, ' ')}: ${value}`)
    } else if (typeof value === 'string' && value.length < 60) {
      parts.push(`${key.replace(/_/g, ' ')}: ${value}`)
    }
  }
  return parts.join(' · ')
}

function FunnelStat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="min-w-[90px] rounded-2xl bg-research-bg px-3 py-2 text-center">
      <p className="font-mono text-lg font-semibold tabular-nums text-research-ink">{value}</p>
      <p className="mt-0.5 text-[11px] font-medium text-research-muted">{label}</p>
    </div>
  )
}

function VerdictRow({
  verdict,
  onTickerClick,
}: {
  verdict: DossierVerdict
  onTickerClick?: (ticker: string) => void
}) {
  return (
    <li className="border-b border-research-line last:border-b-0">
      <button
        type="button"
        onClick={() => onTickerClick?.(verdict.ticker)}
        disabled={!onTickerClick}
        className="flex w-full items-start justify-between gap-4 px-1 py-3 text-left transition hover:bg-research-bg/50 disabled:cursor-default"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-semibold">${verdict.ticker}</span>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                verdict.meets_multi_source_bar
                  ? 'bg-research-green-soft text-research-green'
                  : 'bg-research-bg text-research-muted'
              }`}
            >
              {verdict.meets_multi_source_bar ? 'multi-source' : 'below bar'}
            </span>
          </div>
          <p className="mt-1 text-sm leading-5 text-research-muted">
            {verdict.meets_multi_source_bar
              ? `${verdict.corroborated_claim_count} corroborated claim(s) · ${verdict.strategy_candidates} strategy candidate(s)`
              : verdict.fail_reason}
          </p>
        </div>
        <div className="shrink-0 text-right text-xs text-research-muted">
          <p>
            {verdict.source_count} src · {verdict.news_domain_count} news dom
          </p>
          <p className="mt-0.5">
            {verdict.mention_count} mentions
            {verdict.newest_source_age_hours != null
              ? ` · freshest ${Math.round(verdict.newest_source_age_hours)}h`
              : ''}
          </p>
        </div>
      </button>
    </li>
  )
}

export function RunReportPanel({ report, onTickerClick }: RunReportPanelProps) {
  if (!report) {
    return (
      <div className="rounded-2xl bg-research-bg px-6 py-14 text-center text-sm text-research-muted">
        No run reports yet. The next briefing run will record its full analysis here — including
        days that produce zero recommendations.
      </div>
    )
  }

  const body = report.report || {}
  const stages = body.stages ?? []
  const verdicts = body.dossier_verdicts ?? []
  const dropped = body.narratives_dropped ?? []
  const sportsSetups = body.sports_top_setups ?? []
  const sportsReview = body.sports_scan_review
  const watchlistStage = stages.find((s) => s.stage === 'watchlist')
  const redditStage = stages.find((s) => s.stage === 'reddit_collected')
  const buzzStage = stages.find((s) => s.stage === 'ticker_buzz')
  const marketStage = stages.find((s) => s.stage === 'market_data')
  const multiSource = verdicts.filter((v) => v.meets_multi_source_bar).length

  return (
    <div className="space-y-6">
      <section className="rounded-2xl bg-research-surface px-5 py-5 shadow-soft">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${
              statusStyles[report.status] ?? statusStyles.running
            }`}
          >
            {report.status}
          </span>
          <span className="text-xs text-research-muted">
            {report.run_date} · started{' '}
            {new Date(report.started_at).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </div>
        <p className="mt-3 text-base leading-7 text-research-ink">{report.headline}</p>
        {report.error && (
          <p className="mt-2 rounded-2xl bg-research-red-soft px-4 py-3 font-mono text-xs leading-5 text-research-red">
            {report.error}
          </p>
        )}
        {body.fallback_note && (
          <p className="mt-2 rounded-2xl bg-research-amber-soft px-4 py-3 text-sm text-research-amber">
            {body.fallback_note}
          </p>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          <FunnelStat
            label="Reddit posts"
            value={(redditStage?.finance_posts as number) ?? '—'}
          />
          <FunnelStat
            label="Tickers buzzing"
            value={(buzzStage?.tickers_mentioned as number) ?? '—'}
          />
          <FunnelStat
            label="Watchlist"
            value={
              Array.isArray(watchlistStage?.watchlist)
                ? (watchlistStage!.watchlist as string[]).length
                : '—'
            }
          />
          <FunnelStat label="News items" value={(marketStage?.news_items as number) ?? '—'} />
          <FunnelStat label="Dossiers" value={verdicts.length || '—'} />
          <FunnelStat label="Multi-source" value={verdicts.length ? multiSource : '—'} />
          <FunnelStat label="Model theses" value={body.raw_narrative_count ?? '—'} />
          <FunnelStat label="Narratives" value={body.validated_narrative_count ?? '—'} />
          <FunnelStat label="Low confidence" value={body.low_confidence_narratives ?? '—'} />
          <FunnelStat label="Sports setups" value={sportsSetups.length || '—'} />
        </div>

        {(body.llm_api_mode || body.web_citations != null) && (
          <p className="mt-3 text-xs text-research-muted">
            {body.llm_api_mode ? `LLM mode · ${body.llm_api_mode}` : ''}
            {body.web_citations != null ? ` · ${body.web_citations} web citations` : ''}
          </p>
        )}
      </section>

      {verdicts.length > 0 && (
        <section className="rounded-2xl bg-research-surface px-4 shadow-soft sm:px-5">
          <h2 className="border-b border-research-line px-1 py-4 text-sm font-semibold text-research-ink">
            Ticker verdicts · why each made or missed the bar
          </h2>
          <ul>
            {verdicts.map((v) => (
              <VerdictRow key={v.ticker} verdict={v} onTickerClick={onTickerClick} />
            ))}
          </ul>
        </section>
      )}

      {sportsSetups.length > 0 && (
        <section className="rounded-2xl bg-research-surface px-4 py-4 shadow-soft sm:px-5">
          <h2 className="mb-3 px-1 text-sm font-semibold text-research-ink">
            Sports setups this run
          </h2>
          <ul className="space-y-2 px-1">
            {sportsSetups.map((s, i) => (
              <li key={i} className="rounded-2xl bg-research-bg px-4 py-3">
                <p className="text-sm font-semibold text-research-ink">
                  {s.matchup}
                  <span className="ml-2 font-mono text-xs font-normal tabular-nums text-research-muted">
                    {s.selection}
                    {s.point != null ? ` ${s.point}` : ''} {s.market_label}{' '}
                    {s.best_price > 0 ? '+' : ''}
                    {s.best_price} @ {s.best_bookmaker} · EV {s.ev_pct >= 0 ? '+' : ''}
                    {s.ev_pct.toFixed(1)}%
                  </span>
                  <span
                    className={`ml-2 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                      s.decision === 'bet'
                        ? 'bg-research-green-soft text-research-green'
                        : 'bg-research-amber-soft text-research-amber'
                    }`}
                  >
                    {s.decision}
                  </span>
                </p>
                <p className="mt-1 text-sm text-research-muted">{s.rationale}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {sportsSetups.length === 0 && sportsReview && sportsReview.games_analyzed > 0 && (
        <section className="rounded-2xl bg-research-surface px-4 py-4 shadow-soft sm:px-5">
          <h2 className="mb-2 px-1 text-sm font-semibold text-research-ink">
            Sports scan review · nothing qualified
          </h2>
          <p className="px-1 text-sm text-research-muted">
            {sportsReview.games_analyzed} games analyzed ({sportsReview.decisions.bet} bet ·{' '}
            {sportsReview.decisions.lean} lean · {sportsReview.decisions.pass} pass). Closest
            candidates and the gates they missed:
          </p>
          <ul className="mt-2 space-y-2 px-1">
            {sportsReview.closest_candidates.map((c, i) => (
              <li key={i} className="rounded-2xl bg-research-bg px-4 py-3">
                <p className="text-sm font-semibold text-research-ink">
                  {c.matchup}
                  <span className="ml-2 font-mono text-xs font-normal tabular-nums text-research-muted">
                    {c.selection}
                    {c.point != null ? ` ${c.point}` : ''} {c.market_label} · EV{' '}
                    {c.ev_pct >= 0 ? '+' : ''}
                    {c.ev_pct.toFixed(1)}%
                  </span>
                </p>
                <p className="mt-1 text-sm text-research-muted">{c.why_not_bet}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {dropped.length > 0 && (
        <section className="rounded-2xl bg-research-surface px-4 py-4 shadow-soft sm:px-5">
          <h2 className="mb-3 px-1 text-sm font-semibold text-research-ink">
            Model theses dropped in validation
          </h2>
          <ul className="space-y-2 px-1">
            {dropped.map((d, i) => (
              <li key={i} className="rounded-2xl bg-research-bg px-4 py-3">
                <p className="text-sm font-semibold text-research-ink">
                  {d.title}{' '}
                  <span className="font-mono text-xs font-semibold text-research-green">
                    {d.tickers.map((t) => `$${t}`).join(' ')}
                  </span>
                </p>
                <p className="mt-1 text-sm text-research-muted">{d.reason}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {stages.length > 0 && (
        <section className="rounded-2xl bg-research-surface px-4 py-4 shadow-soft sm:px-5">
          <h2 className="mb-2 px-1 text-sm font-semibold text-research-ink">Stage log</h2>
          <ul className="px-1">
            {stages.map((stage, i) => (
              <li
                key={i}
                className="flex items-start gap-3 border-b border-research-line py-2.5 text-sm last:border-b-0"
              >
                <span className="w-40 shrink-0 font-medium text-research-ink">
                  {stageLabels[stage.stage] ?? stage.stage}
                </span>
                <span className="min-w-0 flex-1 text-research-muted">{stageSummary(stage)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
