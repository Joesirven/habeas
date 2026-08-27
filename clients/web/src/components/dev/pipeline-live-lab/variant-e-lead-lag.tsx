/**
 * Variant E — Lead/lag ladder. DEV lab only (`/dev/pipeline-live?v=e`).
 * Counts only — no PII. Verticals differ by label and position, never hue.
 */
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'

import {
  LIVE_VERTICALS,
  formatCount,
  formatPercent,
  microBarTone,
  stagePercent,
  stageVisual,
  type PipelineLiveStageId,
  type StageCounts,
  type VerticalFixtureRow,
} from './fixture'
import {
  CatalogOnlySection,
  LabFrame,
  MicroBar,
  StageSwitcher,
  StatusLight,
  VerticalName,
} from './chrome'

type LadderRow = {
  vertical: VerticalFixtureRow
  counts: StageCounts
  percent: number
  index: number
}

/** Failures pin above all laggards (most failures first); then least-complete-first; stable by catalog order. */
function sortLadder(rows: readonly LadderRow[]): LadderRow[] {
  return [...rows].sort((a, b) => {
    const aFailed = a.counts.failed > 0 ? 0 : 1
    const bFailed = b.counts.failed > 0 ? 0 : 1
    if (aFailed !== bFailed) return aFailed - bFailed
    if (aFailed === 0 && a.counts.failed !== b.counts.failed) {
      return b.counts.failed - a.counts.failed
    }
    if (a.percent !== b.percent) return a.percent - b.percent
    return a.index - b.index
  })
}

export function VariantELeadLag() {
  const [stage, setStage] = useState<PipelineLiveStageId>('matching')
  const rows = sortLadder(
    LIVE_VERTICALS.map((vertical, index) => {
      const counts = vertical.stages[stage]
      return { vertical, counts, percent: stagePercent(counts), index }
    }),
  )

  return (
    <LabFrame title="E · Lead/lag ladder">
      <div className="space-y-3">
        <StageSwitcher stage={stage} onSelect={setStage} />

        <ul className="space-y-1">
          {rows.map((row) => {
            const visual = stageVisual(row.counts)
            return (
              <li
                key={row.vertical.id}
                className="rounded-md border border-line px-2.5 py-1.5"
              >
                <div className="flex items-center gap-2">
                  <StatusLight tone={visual.light} pulse={visual.pulse} title={visual.state} />
                  <VerticalName vertical={row.vertical} />
                  {row.counts.failed > 0 ? (
                    <Badge variant="fail">Failed {formatCount(row.counts.failed)}</Badge>
                  ) : null}
                  {row.counts.inFlight > 0 ? (
                    <span className="text-[11px] tabular-nums text-mute">
                      {formatCount(row.counts.inFlight)} in flight
                    </span>
                  ) : null}
                  <span className="ml-auto shrink-0 text-[11px] tabular-nums text-mute">
                    {row.counts.total > 0
                      ? `${formatCount(row.counts.success)} / ${formatCount(row.counts.total)}`
                      : 'Not started'}
                  </span>
                  <span className="w-10 shrink-0 text-right text-xs font-semibold tabular-nums text-ink">
                    {formatPercent(row.counts)}
                  </span>
                </div>
                <MicroBar
                  className="mt-1"
                  percent={row.percent}
                  tone={microBarTone(visual)}
                  shimmer={row.counts.inFlight > 0}
                />
              </li>
            )
          })}
        </ul>

        <p className="text-[11px] leading-relaxed text-mute">
          Least complete first — verticals carrying failures pin above all laggards. The top row
          is what is holding the batch up.
        </p>

        <CatalogOnlySection />
      </div>
    </LabFrame>
  )
}
