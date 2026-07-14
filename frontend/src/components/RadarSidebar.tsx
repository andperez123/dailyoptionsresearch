import type { RadarItem } from '../types'

interface RadarSidebarProps {
  items: RadarItem[]
}

export function RadarSidebar({ items }: RadarSidebarProps) {
  return (
    <aside className="rounded-lg border border-terminal-border bg-terminal-panel p-4">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-terminal-muted">
        Buzz Radar
      </h2>
      {items.length === 0 ? (
        <p className="text-sm text-gray-500">No radar tickers yet.</p>
      ) : (
        <ul className="space-y-3">
          {items.map((item) => (
            <li
              key={item.ticker}
              className="rounded border border-terminal-border bg-terminal-bg p-3"
            >
              <div className="mb-1 flex items-center justify-between">
                <span className="font-mono font-bold text-terminal-cyan">${item.ticker}</span>
                <span
                  className={`text-xs font-mono ${
                    item.buzz_delta > 0 ? 'text-terminal-green' : 'text-terminal-muted'
                  }`}
                >
                  {item.buzz_delta > 0 ? '+' : ''}
                  {item.buzz_delta}x buzz
                </span>
              </div>
              <p className="mb-1 text-xs text-terminal-muted">
                {item.mention_count} mentions
              </p>
              <p className="text-xs text-gray-400">{item.note}</p>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
