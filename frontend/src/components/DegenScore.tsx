interface DegenScoreProps {
  score: number
  size?: 'sm' | 'md'
}

export function DegenScore({ score, size = 'md' }: DegenScoreProps) {
  const clamped = Math.min(Math.max(score, 0), 5)
  const textSize = size === 'sm' ? 'text-xs' : 'text-sm'

  return (
    <span className={`inline-flex items-center gap-1.5 ${textSize}`}>
      <span className="flex gap-0.5" aria-label={`Conviction ${clamped} of 5`}>
        {Array.from({ length: 5 }, (_, i) => (
          <span
            key={i}
            className={`h-1.5 w-1.5 rounded-full ${
              i < clamped ? 'bg-research-green' : 'bg-research-line'
            }`}
          />
        ))}
      </span>
      <span className="font-mono font-semibold tabular-nums text-research-muted">{clamped}/5</span>
    </span>
  )
}
