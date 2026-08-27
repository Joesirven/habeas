/**
 * Variant H — Posture strip with per-stage drill. DEV lab only (`/dev/pipeline-live?v=h`).
 * Counts only — no PII. Verticals differ by label and position, never hue.
 */
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

import {
  LIVE_VERTICALS,
  PIPELINE_LIVE_STAGES,
  aggregateStage,
  formatCount,
  formatPercent,
  microBarTone,
  stagePercent,
  stageVisual,
  stageWorkerDone,
  type PipelineLiveStageId,
  type StageCounts,
  type VerticalFixtureRow,
} from './fixture'
import {
  CatalogOnlySection,
  FailedCount,
  LabFrame,
  MicroBar,
  StatusLight,
  VerticalName,
} from './chrome'

type StagePosture = {
  rows: { vertical: VerticalFixtureRow; counts: StageCounts; percent: number }[]
  liveCount: number
  doneCount: number
  failedSum: number
  openSum: number
  notStarted: boolean
  allDone: boolean
  worst: { label: string; percent: number } | null
  worstOpenLabel: string | null
}

function collectStagePosture(stage: PipelineLiveStageId): StagePosture {
  const rows = LIVE_VERTICALS.map((vertical) => {
    const counts = vertical.stages[stage]
    return { vertical, counts, percent: stagePercent(counts) }
  })
  const started = rows.filter((row) => row.counts.total > 0)
  const doneCount = rows.filter((row) => stageWorkerDone(row.counts)).length
  // Worst = least complete among started rows; stable catalog-order ties.
  const worstRow = started.reduce<(typeof started)[number] | null>((acc, row) => {
    if (acc == null) return row
    return row.percent < acc.percent ? row : acc
  }, null)
  const worstOpen = rows.reduce<(typeof rows)[number] | null>((acc, row) => {
    if (row.counts.open <= 0) return acc
    if (acc == null) return row
    return row.counts.open > acc.counts.open ? row : acc
  }, null)
  return {
    rows,
    liveCount: rows.length,
    doneCount,
    failedSum: rows.reduce((sum, row) => sum + row.counts.failed, 0),
    openSum: rows.reduce((sum, row) => sum + row.counts.open, 0),
    notStarted: started.length === 0,
    allDone: rows.length > 0 && doneCount === rows.length,
    worst: worstRow ? { label: worstRow.vertical.label, percent: worstRow.percent } : null,
    worstOpenLabel: worstOpen ? worstOpen.vertical.label : null,
  }
}

function stageSummary(stage: PipelineLiveStageId, posture: StagePosture): string {
  if (posture.notStarted) return 'Not started'
  if (stage === 'review') {
    if (posture.openSum === 0) return posture.allDone ? 'All reviewed' : '0 open'
    return posture.worstOpenLabel
      ? `${formatCount(posture.openSum)} open · ${posture.worstOpenLabel} most open`
      : `${formatCount(posture.openSum)} open`
  }
  if (posture.allDone) return `All ${posture.liveCount} done`
  if (posture.worst) {
    return `${posture.worst.percent}% · ${posture.worst.label} lagging · ${posture.doneCount} of ${posture.liveCount} done`
  }
  return `${posture.doneCount} of ${posture.liveCount} done`
}

export function VariantHPostureStrip() {
  const [expanded, setExpanded] = useState<PipelineLiveStageId | null>(null)

  return (
    <LabFrame title="H · Posture strip + drill">
      <div className="space-y-3">
        <div className="space-y-1">
          {PIPELINE_LIVE_STAGES.map(({ id: stage, label }) => {
            const posture = collectStagePosture(stage)
            const visual = stageVisual(aggregateStage(stage))
            const isOpen = expanded === stage
            const regionId = `pipeline-live-h-drill-${stage}`
            return (
              <div key={stage}>
                <button
                  type="button"
                  aria-expanded={isOpen}
                  aria-controls={regionId}
                  onClick={() => setExpanded((current) => (current === stage ? null : stage))}
                  className={cn(
                    'flex w-full flex-wrap items-center gap-2 rounded-md border border-line px-3 py-2 text-left transition-colors hover:bg-canvas/60',
                    isOpen && 'ring-1 ring-habeas-navy/40',
                  )}
                >
                  <StatusLight tone={visual.light} pulse={visual.pulse} title={visual.state} />
                  <span className="text-xs font-semibold text-ink">{label}</span>
                  {posture.failedSum > 0 ? (
                    <Badge variant="fail">Failed {formatCount(posture.failedSum)}</Badge>
                  ) : null}
                  <span className="text-[11px] text-mute">
                    {stageSummary(stage, posture)}
                  </span>
                  <span className="ml-auto flex items-center gap-2">
                    <span className="text-[11px] tabular-nums text-ink-soft">
                      {posture.doneCount} of {posture.liveCount} done
                    </span>
                    <svg
                      viewBox="0 0 12 12"
                      className={cn(
                        'h-3 w-3 text-mute transition-transform',
                        isOpen && 'rotate-180',
                      )}
                      aria-hidden="true"
                    >
                      <path
                        d="M3 4.5 6 7.5 9 4.5"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </span>
                </button>
                {isOpen ? (
                  <div
                    id={regionId}
                    className="mt-1 rounded-md border border-line bg-canvas/40 p-2"
                  >
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Vertical</TableHead>
                          <TableHead className="text-right">
                            {stage === 'review' ? 'Resolved' : 'Finished'}
                          </TableHead>
                          <TableHead className="text-right">In flight</TableHead>
                          <TableHead className="text-right">
                            {stage === 'review' ? 'Open' : 'Queued'}
                          </TableHead>
                          <TableHead className="text-right">Failed</TableHead>
                          <TableHead className="text-right">%</TableHead>
                          <TableHead className="w-32">Progress</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {posture.rows.map((row) => {
                          const rowVisual = stageVisual(row.counts)
                          return (
                            <TableRow key={row.vertical.id}>
                              <TableCell>
                                <div className="flex items-center gap-2">
                                  <StatusLight
                                    tone={rowVisual.light}
                                    pulse={rowVisual.pulse}
                                    title={rowVisual.state}
                                  />
                                  <VerticalName vertical={row.vertical} />
                                </div>
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                {formatCount(row.counts.success)}
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                {formatCount(row.counts.inFlight)}
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                {formatCount(row.counts.open)}
                              </TableCell>
                              <TableCell className="text-right">
                                <FailedCount count={row.counts.failed} />
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                {formatPercent(row.counts)}
                              </TableCell>
                              <TableCell>
                                <MicroBar
                                  percent={row.percent}
                                  tone={microBarTone(rowVisual)}
                                  shimmer={row.counts.inFlight > 0}
                                />
                              </TableCell>
                            </TableRow>
                          )
                        })}
                      </TableBody>
                    </Table>
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>

        <p className="text-[11px] leading-relaxed text-mute">
          One line per stage — worst vertical plus done-count, collapsed by default. Click a
          line to drill into per-vertical rows for that stage only.
        </p>

        <CatalogOnlySection />
      </div>
    </LabFrame>
  )
}
