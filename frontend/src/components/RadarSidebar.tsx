import type { RadarItem } from '../types'

interface RadarSidebarProps {
  items: RadarItem[]
  onTickerClick?: (ticker: string) => void
}

export function RadarSidebar({ items, onTickerClick }: RadarSidebarProps) {
  if (items.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-research-muted">No buzz tickers yet.</p>
    )
  }

  return (
    <ul>
      {items.map((item) => (
        <li key={item.ticker} className="border-b border-research-line last:border-b-0">
          <button
            type="button"
            onClick={() => onTickerClick?.(item.ticker)}
            disabled={!onTickerClick}
            className="flex w-full items-start justify-between gap-4 px-1 py-4 text-left transition hover:bg-research-bg/50 disabled:cursor-default"
          >
            <div>
              <p className="font-mono text-sm font-semibold">${item.ticker}</p>
              <p className="mt-1 text-sm text-research-muted">{item.note}</p>
            </div>
            <div className="shrink-0 text-right">
              <p
                className={`font-mono text-sm font-semibold tabular-nums ${
                  item.buzz_delta > 0 ? 'text-research-green' : 'text-research-muted'
                }`}
              >
                {item.buzz_delta > 0 ? '+' : ''}
                {item.buzz_delta}x
              </p>
              <p className="mt-0.5 text-xs text-research-muted">{item.mention_count} mentions</p>
            </div>
          </button>
        </li>
      ))}
    </ul>
  )
}
