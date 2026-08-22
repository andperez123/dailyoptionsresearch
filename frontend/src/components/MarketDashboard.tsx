import type { MarketDashboardData } from '../types'

interface MarketDashboardProps {
  dashboard: MarketDashboardData
  onTickerClick?: (ticker: string) => void
}

function PctChange({ value }: { value: number | null | undefined }) {
  if (value == null) return null
  const positive = value >= 0
  return (
    <span
      className={`font-mono text-xs font-semibold tabular-nums ${
        positive ? 'text-research-green' : 'text-research-red'
      }`}
    >
      {positive ? '+' : ''}
      {value.toFixed(2)}%
    </span>
  )
}

export function MarketDashboard({ dashboard, onTickerClick }: MarketDashboardProps) {
  const indices = dashboard.indices ?? []
  const movers = dashboard.watchlist_movers ?? []
  const ivExtremes = dashboard.iv_extremes ?? []
  const flow = dashboard.unusual_flow ?? []
  const earnings = dashboard.earnings_ahead ?? []
  const buzz = dashboard.buzz_leaders ?? []

  const hasContent =
    indices.length > 0 ||
    movers.length > 0 ||
    ivExtremes.length > 0 ||
    flow.length > 0 ||
    earnings.length > 0 ||
    buzz.length > 0

  if (!hasContent) return null

  return (
    <section className="rounded-2xl bg-research-surface px-4 py-4 shadow-soft sm:px-5">
      {indices.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-research-line pb-3">
          {indices.map((idx) => (
            <span key={idx.symbol} className="flex items-baseline gap-1.5">
              <span className="font-mono text-xs font-semibold text-research-ink">
                {idx.symbol}
              </span>
              <span className="font-mono text-xs tabular-nums text-research-muted">
                {idx.price.toFixed(2)}
              </span>
              <PctChange value={idx.pct_change} />
            </span>
          ))}
        </div>
      )}

      <div className="grid gap-x-6 gap-y-4 pt-4 sm:grid-cols-2 lg:grid-cols-3">
        {movers.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-research-muted">
              Watchlist movers
            </p>
            <ul className="space-y-1">
              {movers.map((m) => (
                <li key={m.ticker} className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => onTickerClick?.(m.ticker)}
                    className="font-mono text-xs font-semibold text-research-ink hover:text-research-blue"
                  >
                    {m.ticker}
                  </button>
                  <PctChange value={m.pct_change} />
                </li>
              ))}
            </ul>
          </div>
        )}

        {ivExtremes.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-research-muted">
              IV extremes
            </p>
            <ul className="space-y-1.5">
              {ivExtremes.map((iv) => (
                <li key={iv.ticker} className="text-xs leading-5">
                  <button
                    type="button"
                    onClick={() => onTickerClick?.(iv.ticker)}
                    className="font-mono font-semibold text-research-ink hover:text-research-blue"
                  >
                    {iv.ticker}
                  </button>{' '}
                  <span className="text-research-muted">
                    IV rank {(iv.iv_rank * 100).toFixed(0)} · {iv.read}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {flow.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-research-muted">
              Unusual flow
            </p>
            <ul className="space-y-1.5">
              {flow.map((f) => (
                <li key={f.ticker} className="text-xs leading-5">
                  <button
                    type="button"
                    onClick={() => onTickerClick?.(f.ticker)}
                    className="font-mono font-semibold text-research-ink hover:text-research-blue"
                  >
                    {f.ticker}
                  </button>{' '}
                  <span className="text-research-muted">
                    P/C {f.put_call_ratio.toFixed(2)} · {f.read}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {earnings.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-research-muted">
              Earnings ahead
            </p>
            <ul className="flex flex-wrap gap-2">
              {earnings.map((e) => (
                <li key={`${e.ticker}-${e.date}`}>
                  <button
                    type="button"
                    onClick={() => onTickerClick?.(e.ticker)}
                    className="rounded-full bg-research-bg px-2.5 py-1 font-mono text-[11px] font-semibold text-research-ink hover:text-research-blue"
                  >
                    {e.ticker} <span className="font-sans font-normal text-research-muted">{e.date}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {buzz.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-research-muted">
              Buzz leaders
            </p>
            <ul className="space-y-1">
              {buzz.map((b) => (
                <li key={b.ticker} className="flex items-center justify-between gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => onTickerClick?.(b.ticker)}
                    className="font-mono font-semibold text-research-ink hover:text-research-blue"
                  >
                    {b.ticker}
                  </button>
                  <span className="font-mono tabular-nums text-research-muted">
                    z {b.buzz_z.toFixed(1)} · {b.mentions}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
