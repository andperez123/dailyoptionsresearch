interface ScoreBadgeProps {
  label: string
  score: number
  max?: number
}

export function ScoreBadge({ label, score, max = 10 }: ScoreBadgeProps) {
  const pct = score / max
  const color =
    pct >= 0.8
      ? 'text-fuchsia-400 border-fuchsia-500/40'
      : pct >= 0.6
        ? 'text-terminal-red border-terminal-red/40'
        : pct >= 0.4
          ? 'text-terminal-yellow border-terminal-yellow/40'
          : 'text-terminal-muted border-terminal-border'

  return (
    <span
      className={`inline-flex items-center gap-1 rounded border bg-terminal-bg px-1.5 py-0.5 font-mono text-[10px] ${color}`}
    >
      <span className="opacity-70">{label}</span>
      <span className="font-bold">{score}</span>
    </span>
  )
}

export function DirectionBadge({ direction }: { direction: string }) {
  const colors: Record<string, string> = {
    bullish: 'text-terminal-green',
    bearish: 'text-terminal-red',
    volatility: 'text-terminal-cyan',
    mixed: 'text-terminal-yellow',
    neutral: 'text-terminal-muted',
  }
  return (
    <span className={`text-[10px] uppercase font-semibold ${colors[direction] || colors.neutral}`}>
      {direction}
    </span>
  )
}

export { formatStrategy, formatTime } from '../lib/format'
