import { cn } from '@/lib/utils'

export type MatchingResultsLabToolbarProps = {
  className?: string
}

/** Header toolbar slot — Requests lives in top nav, not here. */
export function MatchingResultsLabToolbar({
  className,
}: MatchingResultsLabToolbarProps) {
  return <div className={cn('flex flex-wrap items-center gap-2', className)} />
}
