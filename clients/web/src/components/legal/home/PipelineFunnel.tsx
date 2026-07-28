import { Link } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { COARSE_STAGE_ORDER, stageLabel } from '@/lib/legalJourneyLabels'
import { cn } from '@/lib/utils'

type PipelineFunnelProps = {
  stages: LegalPortfolio['stage_reach_counts']
  onStageClick?: (stage: string) => void
}

export function PipelineFunnel({ stages, onStageClick }: PipelineFunnelProps) {
  const byStage = new Map(stages.map((row) => [row.stage, row]))
  const ordered = COARSE_STAGE_ORDER.map((key) => {
    const row = byStage.get(key)
    return {
      stage: key,
      reached: row?.reached_count ?? 0,
      dropped: row?.dropped_count ?? 0,
    }
  })
  const topReached = Math.max(1, ordered[0]?.reached ?? 1)

  return (
    <div className="space-y-1" role="img" aria-label="Pipeline stage reach funnel">
      {ordered.map((row, index) => {
        const widthPct = Math.max((row.reached / topReached) * 100, row.reached > 0 ? 12 : 4)
        const prev = index > 0 ? ordered[index - 1] : null
        const showDrop = prev && prev.dropped > 0

        return (
          <div key={row.stage} className="space-y-0.5">
            {showDrop ? (
              <p className="pl-1 text-[0.6rem] tabular-nums text-mute">
                −{prev!.dropped} did not reach {stageLabel(row.stage)}
              </p>
            ) : null}
            <div className="flex items-center gap-2">
              <span className="w-[7.5rem] shrink-0 text-right text-[0.65rem] leading-tight text-ink-soft">
                {stageLabel(row.stage)}
              </span>
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <div className="flex h-7 flex-1 justify-center">
                  <Link
                    to="/requests"
                    search={{ stage: row.stage }}
                    className={cn(
                      'flex h-full items-center justify-center rounded bg-habeas-navy/80 px-2 text-[0.65rem] font-medium tabular-nums text-white transition-opacity hover:bg-habeas-navy focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid',
                      row.reached === 0 && 'opacity-30',
                    )}
                    style={{ width: `${widthPct}%`, minWidth: row.reached > 0 ? '2.5rem' : '1.5rem' }}
                    onClick={(event) => {
                      if (onStageClick) {
                        event.preventDefault()
                        onStageClick(row.stage)
                      }
                    }}
                  >
                    {row.reached}
                  </Link>
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
