interface DegenScoreProps {
  score: number
  size?: 'sm' | 'md'
}

export function DegenScore({ score, size = 'md' }: DegenScoreProps) {
  const colors = [
    'text-terminal-muted',
    'text-green-400',
    'text-terminal-yellow',
    'text-orange-400',
    'text-terminal-red',
    'text-fuchsia-400',
  ]
  const color = colors[Math.min(Math.max(score, 1), 5)]
  const textSize = size === 'sm' ? 'text-xs' : 'text-sm'

  return (
    <span
      className={`inline-flex items-center gap-1 rounded border border-terminal-border bg-terminal-panel px-2 py-0.5 font-mono ${textSize} ${color}`}
    >
      <span className="opacity-60">DEGEN</span>
      <span className="font-bold">{score}/5</span>
    </span>
  )
}
