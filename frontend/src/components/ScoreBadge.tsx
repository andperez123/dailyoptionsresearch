interface ScoreBadgeProps {
  label: string
  score: number
  max?: number
}

export function ScoreBadge({ label, score, max = 10 }: ScoreBadgeProps) {
  const pct = score / max
  const tone =
    pct >= 0.8
      ? 'bg-research-green-soft text-research-green'
      : pct >= 0.5
        ? 'bg-research-amber-soft text-research-amber'
        : 'bg-research-bg text-research-muted'

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-xs font-semibold tabular-nums ${tone}`}
    >
      <span className="opacity-70">{label}</span>
      {score}
    </span>
  )
}

export function DirectionBadge({ direction }: { direction: string }) {
  const styles: Record<string, string> = {
    bullish: 'bg-research-green-soft text-research-green',
    bearish: 'bg-research-red-soft text-research-red',
    volatility: 'bg-research-blue-soft text-research-blue',
    mixed: 'bg-research-amber-soft text-research-amber',
    neutral: 'bg-research-bg text-research-muted',
  }

  return (
    <span
      className={`rounded-md px-1.5 py-0.5 text-xs font-semibold capitalize ${
        styles[direction] || styles.neutral
      }`}
    >
      {direction}
    </span>
  )
}

export { formatStrategy, formatTime } from '../lib/format'
