import { useState } from 'react'

import { cn } from '@/lib/utils'

import {
  CATALOG_ONLY_VERTICALS,
  LIVE_VERTICALS,
  PIPELINE_LIVE_STAGES,
  aggregateStage,
  formatCount,
  stagePercent,
  stageVisual,
  type PipelineLiveStageId,
} from './fixture'
import { LabFrame, StageSwitcher } from './chrome'

export function VariantCSlicedBar() {
  const [stage, setStage] = useState<PipelineLiveStageId>('matching')
  const aggregate = aggregateStage(stage)
  const overallPercent = stagePercent(aggregate)
  const stageMeta = PIPELINE_LIVE_STAGES.find((entry) => entry.id === stage)

  return (
    <LabFrame title="C · Segmented stage bar, vertical slices">
      <div className="space-y-3">
        <StageSwitcher stage={stage} onSelect={setStage} />

        <div>
          <div className="flex flex-wrap items-baseline gap-2">
            <p className="text-sm font-semibold text-ink">
              {stageMeta?.label} {aggregate.total > 0 ? `${overallPercent}%` : '—'} overall
            </p>
            <p className="text-[11px] tabular-nums text-mute">
              {formatCount(aggregate.success)} of {formatCount(aggregate.total)} finished
              {aggregate.inFlight > 0
                ? ` · ${formatCount(aggregate.inFlight)} in flight`
                : ''}
              {aggregate.failed > 0 ? ` · ${formatCount(aggregate.failed)} failed` : ''}
            </p>
          </div>

          <div
            className="mt-2 flex h-6 items-stretch gap-px"
            role="img"
            aria-label={`${stageMeta?.label} progress sliced by vertical`}
          >
            {LIVE_VERTICALS.map((vertical, index) => {
              const counts = vertical.stages[stage]
              const visual = stageVisual(counts)
              const percent = stagePercent(counts)
              const fill =
                visual.state === 'complete'
                  ? visual.light === 'amber'
                    ? 'bg-amber-500'
                    : 'bg-emerald-600'
                  : 'bg-habeas-navy'
              return (
                <div
                  key={vertical.id}
                  className={cn(
                    'relative min-w-0 flex-1 overflow-hidden bg-line/40',
                    index === 0 && 'rounded-l',
                    index === LIVE_VERTICALS.length - 1 && 'rounded-r',
                  )}
                  title={`${vertical.label}: ${counts.total > 0 ? `${percent}%` : 'not started'}`}
                >
                  <div
                    className={cn('h-full transition-[width]', fill)}
                    style={{ width: `${percent}%` }}
                  />
                  {counts.inFlight > 0 ? (
                    <div className="pointer-events-none absolute inset-0 animate-pulse bg-gradient-to-r from-transparent via-white/50 to-transparent" />
                  ) : null}
                </div>
              )
            })}
          </div>

          <div className="mt-1 flex gap-px">
            {LIVE_VERTICALS.map((vertical) => {
              const counts = vertical.stages[stage]
              return (
                <div key={vertical.id} className="min-w-0 flex-1">
                  <p className="truncate text-[10px] font-medium text-ink-soft">
                    {vertical.label}
                  </p>
                  <p className="text-[10px] tabular-nums text-mute">
                    {counts.total > 0 ? `${stagePercent(counts)}%` : 'not started'}
                    {counts.failed > 0 ? (
                      <span className="text-red-800"> · {formatCount(counts.failed)} failed</span>
                    ) : null}
                  </p>
                </div>
              )
            })}
          </div>
        </div>

        <p className="text-[11px] leading-relaxed text-mute">
          Slices are equal width and labeled by position — fill is each vertical’s own percent in
          the single stage tone. Catalog-only (
          {CATALOG_ONLY_VERTICALS.map((row) => row.label).join(' · ')}) carry no slices — matching
          is not live.
        </p>
      </div>
    </LabFrame>
  )
}
