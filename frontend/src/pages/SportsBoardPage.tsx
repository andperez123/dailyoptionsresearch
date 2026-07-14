import { useEffect, useState } from 'react'
import { getSports } from '../api'
import type { SportsBoardResponse } from '../types'
import { formatTime } from '../lib/format'

export function SportsBoardPage() {
  const [board, setBoard] = useState<SportsBoardResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getSports(controller.signal)
      .then((data) => {
        setBoard(data)
        setError(null)
      })
      .catch((err) => {
        if (err instanceof Error && err.name !== 'AbortError') {
          setError(err.message)
        }
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [])

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <p className="animate-pulse font-mono text-terminal-green">Loading sports board...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded border border-terminal-red/40 p-4 text-sm text-terminal-red">
        {error}
      </div>
    )
  }

  if (!board?.configured) {
    return (
      <div className="rounded border border-dashed border-terminal-border p-12 text-center">
        <h1 className="mb-2 text-lg font-bold">Sports Board</h1>
        <p className="text-sm text-terminal-muted">{board?.message || 'Odds API not configured'}</p>
        <p className="mt-4 text-xs text-gray-500">
          Add <code className="text-terminal-cyan">ODDS_API_KEY</code> to .env — free tier at the-odds-api.com
        </p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold">Sports Board</h1>
          <p className="text-[10px] text-terminal-muted">
            Observations only — not picks · Updated {formatTime(board.data_timestamp)}
          </p>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {board.games.map((game) => (
          <article
            key={`${game.commence_time}-${game.away_team}-${game.home_team}`}
            className="rounded border border-terminal-border bg-terminal-panel p-4 text-sm"
          >
            <div className="mb-2 flex items-start justify-between">
              <div>
                <span className="text-[10px] uppercase text-terminal-yellow">{game.sport}</span>
                <h3 className="font-bold text-white">
                  {game.away_team} @ {game.home_team}
                </h3>
                <p className="text-[10px] text-terminal-muted">
                  {new Date(game.commence_time).toLocaleString()}
                </p>
              </div>
              {game.line_movement && (
                <span className="rounded border border-terminal-cyan/40 px-2 py-0.5 text-[10px] text-terminal-cyan">
                  moved
                </span>
              )}
            </div>

            <div className="mb-3 space-y-2">
              {game.lines.slice(0, 4).map((line) => (
                <div
                  key={`${line.bookmaker}-${line.market}`}
                  className="rounded bg-terminal-bg p-2 text-xs"
                >
                  <span className="text-terminal-muted">
                    {line.bookmaker} · {line.market}
                  </span>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {line.outcomes.map((o) => (
                      <span key={`${o.name}-${o.price}`} className="font-mono text-gray-300">
                        {o.name}: {o.price > 0 ? '+' : ''}
                        {o.price}
                        {o.point != null ? ` (${o.point})` : ''}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {game.opening_line && (
              <p className="mb-1 text-[10px] text-terminal-muted">
                Opening line recorded · compare to current for movement
              </p>
            )}

            {game.ai_context && (
              <p className="rounded border border-terminal-yellow/20 bg-terminal-bg p-2 text-xs text-gray-400">
                <span className="text-terminal-yellow">Context:</span> {game.ai_context}
              </p>
            )}
          </article>
        ))}
      </div>

      {board.games.length === 0 && (
        <p className="text-center text-sm text-terminal-muted">No games loaded. Worker will refresh on schedule.</p>
      )}
    </div>
  )
}
