import { useEffect, useMemo, useState } from 'react'
import { getSports } from '../api'
import type { SportsBoardResponse } from '../types'
import { formatTime } from '../lib/format'

type SortMode = 'relevance' | 'soonest'

export function SportsBoardPage() {
  const [board, setBoard] = useState<SportsBoardResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sportFilter, setSportFilter] = useState<string>('all')
  const [sortBy, setSortBy] = useState<SortMode>('relevance')

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

  const sportOptions = useMemo(() => {
    if (!board) return []
    return Array.from(new Set(board.games.map((g) => g.sport_key || g.sport))).sort()
  }, [board])

  const visibleGames = useMemo(() => {
    if (!board) return []
    let games = [...board.games]
    if (sportFilter !== 'all') {
      games = games.filter((g) => (g.sport_key || g.sport) === sportFilter)
    }
    if (sortBy === 'soonest') {
      games.sort(
        (a, b) => new Date(a.commence_time).getTime() - new Date(b.commence_time).getTime(),
      )
    } else {
      games.sort((a, b) => b.relevance_score - a.relevance_score)
    }
    return games
  }, [board, sportFilter, sortBy])

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
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold">Sports Board</h1>
          <p className="text-[10px] text-terminal-muted">
            Observations only — not picks · Updated {formatTime(board.data_timestamp)}
            {board.quota_remaining != null ? ` · Quota ${board.quota_remaining} left` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <select
            value={sportFilter}
            onChange={(e) => setSportFilter(e.target.value)}
            className="rounded border border-terminal-border bg-terminal-bg px-2 py-1"
          >
            <option value="all">All competitions</option>
            {sportOptions.map((sport) => (
              <option key={sport} value={sport}>
                {sport}
              </option>
            ))}
          </select>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortMode)}
            className="rounded border border-terminal-border bg-terminal-bg px-2 py-1"
          >
            <option value="relevance">Sort: relevance</option>
            <option value="soonest">Sort: kickoff</option>
          </select>
        </div>
      </div>

      {board.featured_competitions.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {board.featured_competitions.map((comp) => (
            <span
              key={comp}
              className="rounded border border-terminal-yellow/30 px-2 py-1 text-[10px] uppercase text-terminal-yellow"
            >
              Featured: {comp}
            </span>
          ))}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {visibleGames.map((game) => (
          <article
            key={game.event_key || `${game.commence_time}-${game.away_team}-${game.home_team}`}
            className="rounded border border-terminal-border bg-terminal-panel p-4 text-sm"
          >
            <div className="mb-2 flex items-start justify-between gap-2">
              <div>
                <span className="text-[10px] uppercase text-terminal-yellow">
                  {game.sport_title || game.sport}
                </span>
                <h3 className="font-bold text-white">
                  {game.away_team} @ {game.home_team}
                </h3>
                <p className="text-[10px] text-terminal-muted">
                  {new Date(game.commence_time).toLocaleString()}
                  {game.is_live_window ? ' · live window' : ''}
                </p>
              </div>
              <div className="text-right text-[10px]">
                <p className="font-mono text-terminal-cyan">score {game.relevance_score.toFixed(1)}</p>
                {game.line_movement && (
                  <span className="rounded border border-terminal-cyan/40 px-2 py-0.5 text-terminal-cyan">
                    moved
                  </span>
                )}
              </div>
            </div>

            {game.relevance_factors && (
              <p className="mb-2 text-[10px] text-gray-500">
                Relevance: proximity {game.relevance_factors.proximity ?? 0} · stage{' '}
                {game.relevance_factors.stage ?? 0} · news {game.relevance_factors.news_hits ?? 0}
              </p>
            )}

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

            {game.movement_delta && (
              <p className="mb-2 text-[10px] text-terminal-cyan">{game.movement_delta}</p>
            )}

            {game.news_context.length > 0 && (
              <div className="mb-2 space-y-1 border-t border-terminal-border pt-2">
                <p className="text-[10px] uppercase text-terminal-muted">Matched news</p>
                {game.news_context.slice(0, 3).map((article) => (
                  <a
                    key={article.url}
                    href={article.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block text-xs text-terminal-cyan hover:underline"
                  >
                    {article.title}
                  </a>
                ))}
              </div>
            )}

            {game.ai_context && (
              <p className="rounded border border-terminal-yellow/20 bg-terminal-bg p-2 text-xs text-gray-400">
                <span className="text-terminal-yellow">Context:</span> {game.ai_context}
              </p>
            )}
          </article>
        ))}
      </div>

      {visibleGames.length === 0 && (
        <p className="text-center text-sm text-terminal-muted">No games loaded. Worker will refresh on schedule.</p>
      )}
    </div>
  )
}
