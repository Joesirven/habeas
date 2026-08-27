import { Fragment } from 'react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

import {
  LIVE_VERTICALS,
  PIPELINE_LIVE_STAGES,
  formatCount,
  microBarTone,
  stagePercent,
  stageVisual,
  verticalCurrentStage,
} from './fixture'
import {
  CatalogOnlySection,
  LabFrame,
  MicroBar,
  StatusLight,
  VerticalName,
} from './chrome'

export function VariantDJourneyClusters() {
  return (
    <LabFrame title="D · Per-vertical journey clusters">
      <div className="space-y-3">
        <ul className="space-y-2">
          {LIVE_VERTICALS.map((vertical) => {
            const current = verticalCurrentStage(vertical)
            return (
              <li
                key={vertical.id}
                className="rounded-md border border-line bg-white px-3 py-2.5"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <VerticalName vertical={vertical} />
                  {vertical.id === 'test' ? <Badge variant="default">Test vertical</Badge> : null}
                  {current === null ? <Badge variant="ok">Complete</Badge> : null}
                </div>
                <div className="mt-2 flex items-stretch gap-1">
                  {PIPELINE_LIVE_STAGES.map((stage, index) => {
                    const counts = vertical.stages[stage.id]
                    const visual = stageVisual(counts)
                    const isCurrent = current === stage.id
                    const percent = stagePercent(counts)
                    return (
                      <Fragment key={stage.id}>
                        {index > 0 ? (
                          <span className="self-center px-0.5 text-[10px] text-mute" aria-hidden>
                            →
                          </span>
                        ) : null}
                        <div
                          className={cn(
                            'min-w-0 flex-1 rounded px-2 py-1.5',
                            isCurrent && 'border-l-2 border-l-emerald-500 bg-panel/40',
                          )}
                        >
                          <div className="flex min-w-0 items-center gap-1.5">
                            <StatusLight
                              tone={visual.light}
                              pulse={isCurrent && visual.state === 'running'}
                              title={visual.state}
                            />
                            <span className="truncate text-[0.6rem] font-medium uppercase tracking-wide text-ink-soft">
                              {stage.label}
                            </span>
                            <span className="ml-auto shrink-0 text-[11px] font-medium tabular-nums text-ink">
                              {counts.total > 0 ? `${percent}%` : '—'}
                            </span>
                          </div>
                          <MicroBar
                            className="mt-1"
                            percent={percent}
                            tone={microBarTone(visual)}
                            shimmer={counts.inFlight > 0}
                          />
                          <p className="mt-1 text-[10px] tabular-nums text-mute">
                            {counts.total > 0
                              ? `${formatCount(counts.success)} of ${formatCount(counts.total)}`
                              : 'not started'}
                            {counts.failed > 0 ? (
                              <span className="text-red-800">
                                {' '}
                                · {formatCount(counts.failed)} failed
                              </span>
                            ) : null}
                            {stage.id === 'review' && counts.open > 0 ? (
                              <span className="text-amber-900">
                                {' '}
                                · {formatCount(counts.open)} need review
                              </span>
                            ) : null}
                          </p>
                        </div>
                      </Fragment>
                    )
                  })}
                </div>
              </li>
            )
          })}
        </ul>

        <CatalogOnlySection />
      </div>
    </LabFrame>
  )
}
