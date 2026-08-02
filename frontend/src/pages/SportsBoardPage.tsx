import { useEffect, useMemo, useState } from 'react'
import { getSports, getSportsRecord } from '../api'
import type { SportsBetRecordResponse, SportsBoardResponse, SportsGameCard } from '../types'
import { formatTime } from '../lib/format'
import { BetDecisionBadge, BetDecisionPanel } from '../components/BetDecisionPanel'

const STATUS_COLORS: Record<string, string> = {
  won: 'text-research-green',
  lost: 'text-research-red',
  push: 'text-research-muted',
  void: 'text-research-muted',
  open: 'text-research-blue',
}

function TrackRecordStrip({ record }: { record: SportsBetRecordResponse }) {
  const [open, setOpen] = useState(false)
  const { stats, entries } = record
  if (entries.length === 0) return null

  return (
    <section className="mb-8 rounded-2xl bg-research-surface px-5 py-4 shadow-soft">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full flex-wrap items-center justify-between gap-3 text-left"
      >
        <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
          <span className="text-sm font-semibold uppercase tracking-wide text-research-muted">
            Track record
          </span>
          <span className="font-mono text-sm font-semibold tabular-nums">
            {stats.won}-{stats.lost}
            {stats.push > 0 ? `-${stats.push}` : ''}
            {stats.hit_rate != null ? ` (${(stats.hit_rate * 100).toFixed(0)}%)` : ''}
          </span>
          <span
            className={`font-mono text-sm font-semibold tabular-nums ${
              stats.units_pnl >= 0 ? 'text-research-green' : 'text-research-red'
            }`}
          >
            {stats.units_pnl >= 0 ? '+' : ''}
            {stats.units_pnl}u
          </span>
          {stats.avg_clv_pct != null && (
            <span className="text-xs text-research-muted">
              avg CLV{' '}
              <span
                className={`font-mono font-semibold tabular-nums ${
                  stats.avg_clv_pct >= 0 ? 'text-research-green' : 'text-research-red'
                }`}
              >
                {stats.avg_clv_pct >= 0 ? '+' : ''}
                {stats.avg_clv_pct}%
              </span>
            </span>
          )}
          {stats.open > 0 && (
            <span className="text-xs text-research-muted">{stats.open} open</span>
          )}
        </div>
        <span className="text-xs text-research-muted">{open ? 'Hide' : 'Show'} bets</span>
      </button>

      {open && (
        <div className="animate-fade-up mt-4 space-y-2">
          {entries.slice(0, 20).map((entry) => (
            <div
              key={entry.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-research-bg px-4 py-2.5 text-sm"
            >
              <div>
                <span className="font-medium text-research-ink">{entry.matchup}</span>
                <span className="ml-2 font-mono text-xs tabular-nums text-research-muted">
                  {entry.selection} {entry.market} {entry.best_price > 0 ? '+' : ''}
                  {entry.best_price} · {entry.stake_units}u
                </span>
              </div>
              <div className="flex items-center gap-3">
                {entry.clv_pct != null && (
                  <span
                    className={`font-mono text-xs tabular-nums ${
                      entry.clv_pct >= 0 ? 'text-research-green' : 'text-research-red'
                    }`}
                  >
                    CLV {entry.clv_pct >= 0 ? '+' : ''}
                    {entry.clv_pct}%
                  </span>
                )}
                <span
                  className={`text-xs font-bold uppercase ${STATUS_COLORS[entry.status] ?? ''}`}
                >
                  {entry.status}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

type SortMode = 'relevance' | 'soonest'

function GameRow({ game }: { game: SportsGameCard }) {
  const [open, setOpen] = useState(false)

  return (
    <article className="border-b border-research-line last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-start justify-between gap-4 px-1 py-5 text-left"
      >
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-research-muted">
            {game.sport_title || game.sport}
            {game.is_live_window ? ' · live window' : ''}
          </p>
          <h3 className="mt-1 text-[15px] font-semibold text-research-ink">
            {game.away_team} @ {game.home_team}
          </h3>
          <p className="mt-0.5 text-sm text-research-muted">
            {new Date(game.commence_time).toLocaleString()}
          </p>
          {game.bet_decision && (
            <div className="mt-2">
              <BetDecisionBadge decision={game.bet_decision} />
            </div>
          )}
          {game.line_movement && (
            <p className="mt-2 text-xs font-medium text-research-blue">Line moved</p>
          )}
        </div>
        <div className="text-right">
          <p className="font-mono text-sm font-semibold tabular-nums text-research-ink">
            {game.relevance_score.toFixed(1)}
          </p>
          <p className="mt-0.5 text-xs text-research-muted">{open ? 'Hide' : 'Details'}</p>
        </div>
      </button>

      {open && (
        <div className="animate-fade-up space-y-4 px-1 pb-5">
          {game.bet_decision && <BetDecisionPanel decision={game.bet_decision} />}

          <div className="space-y-2">
            {game.lines.slice(0, 4).map((line) => (
              <div
                key={`${line.bookmaker}-${line.market}`}
                className="rounded-2xl bg-research-bg px-4 py-3 text-sm"
              >
                <p className="text-xs text-research-muted">
                  {line.bookmaker} · {line.market}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
                  {line.outcomes.map((o) => (
                    <span key={`${o.name}-${o.price}`} className="font-mono text-sm tabular-nums">
                      {o.name}{' '}
                      <span className="font-semibold">
                        {o.price > 0 ? '+' : ''}
                        {o.price}
                      </span>
                      {o.point != null ? ` (${o.point})` : ''}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {game.movement_delta && (
            <p className="text-sm text-research-muted">{game.movement_delta}</p>
          )}

          {game.news_context.length > 0 && (
            <div className="space-y-1.5">
              {game.news_context.slice(0, 3).map((article) => (
                <a
                  key={article.url}
                  href={article.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block text-sm font-medium text-research-blue hover:underline"
                >
                  {article.title}
                </a>
              ))}
            </div>
          )}

          {game.ai_context && (
            <p className="rounded-2xl bg-research-amber-soft/70 px-4 py-3 text-sm leading-6 text-research-ink">
              {game.ai_context}
            </p>
          )}
        </div>
      )}
    </article>
  )
}

export function SportsBoardPage() {
  const [board, setBoard] = useState<SportsBoardResponse | null>(null)
  const [record, setRecord] = useState<SportsBetRecordResponse | null>(null)
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
    getSportsRecord(controller.signal)
      .then(setRecord)
      .catch(() => {
        // Track record is supplementary; the board still renders without it.
      })
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
        <p className="animate-pulse text-sm text-research-muted">Loading sports…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-2xl bg-research-red-soft px-4 py-3 text-sm text-research-red">
        {error}
      </div>
    )
  }

  if (!board?.configured) {
    return (
      <div className="rounded-2xl bg-research-bg px-6 py-16 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">Sports</h1>
        <p className="mx-auto mt-3 max-w-md text-sm text-research-muted">
          {board?.message || 'Odds API not configured'}
        </p>
      </div>
    )
  }

  return (
    <div className="animate-fade-up">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Sports</h1>
          <p className="mt-1 text-sm text-research-muted">
            Decisions within {board.bet_horizon_days} days · Updated {formatTime(board.data_timestamp)}
            {board.quota_remaining != null ? ` · ${board.quota_remaining} left` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            value={sportFilter}
            onChange={(e) => setSportFilter(e.target.value)}
            className="rounded-full border border-research-line bg-research-surface px-3 py-1.5 text-xs font-medium"
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
            className="rounded-full border border-research-line bg-research-surface px-3 py-1.5 text-xs font-medium"
          >
            <option value="relevance">Relevance</option>
            <option value="soonest">Kickoff</option>
          </select>
        </div>
      </div>

      {record && <TrackRecordStrip record={record} />}

      {board.best_bets.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-research-muted">
            Best bets · next {board.bet_horizon_days} days
          </h2>
          <div className="space-y-3">
            {board.best_bets.map((bet) => (
              <div key={`${bet.event_key}-${bet.market}-${bet.selection}`}>
                <p className="mb-1.5 text-sm font-semibold text-research-ink">
                  {bet.matchup}
                  <span className="ml-2 text-xs font-normal text-research-muted">
                    {bet.sport_title} · {new Date(bet.commence_time).toLocaleString()}
                  </span>
                </p>
                <BetDecisionPanel decision={bet} />
              </div>
            ))}
          </div>
        </section>
      )}

      {board.featured_competitions.length > 0 && (
        <div className="mb-5 flex flex-wrap gap-2">
          {board.featured_competitions.map((comp) => (
            <span
              key={comp}
              className="rounded-full bg-research-amber-soft px-3 py-1 text-xs font-medium text-research-amber"
            >
              {comp}
            </span>
          ))}
        </div>
      )}

      {visibleGames.length === 0 ? (
        <div className="rounded-2xl bg-research-bg px-6 py-14 text-center text-sm text-research-muted">
          No games loaded yet.
        </div>
      ) : (
        <div className="rounded-2xl bg-research-surface px-4 shadow-soft sm:px-5">
          {visibleGames.map((game) => (
            <GameRow
              key={game.event_key || `${game.commence_time}-${game.away_team}-${game.home_team}`}
              game={game}
            />
          ))}
        </div>
      )}
    </div>
  )
}
