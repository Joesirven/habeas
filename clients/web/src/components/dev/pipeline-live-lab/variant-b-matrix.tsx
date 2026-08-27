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
  CATALOG_ONLY_VERTICALS,
  LIVE_VERTICALS,
  PIPELINE_LIVE_STAGES,
  formatCount,
  stagePercent,
  stageVisual,
  type PipelineLiveStageId,
  type StageCounts,
  type VerticalFixtureRow,
} from './fixture'
import { LabFrame, StatusLight, VerticalName } from './chrome'

type CellRef = { verticalId: string; stage: PipelineLiveStageId }

function MatrixCell({
  vertical,
  stage,
  selected,
  onSelect,
}: {
  vertical: VerticalFixtureRow
  stage: PipelineLiveStageId
  selected: boolean
  onSelect: () => void
}) {
  const counts = vertical.stages[stage]
  const visual = stageVisual(counts)

  if (counts.total <= 0) {
    return (
      <div className="rounded px-2 py-1.5">
        <div className="flex items-center gap-1.5">
          <StatusLight tone="mute" />
          <span className="text-sm tabular-nums text-mute">—</span>
        </div>
        <p className="mt-0.5 text-[10px] text-mute">not started</p>
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        'w-full rounded px-2 py-1.5 text-left transition-colors hover:bg-panel/50',
        selected && 'bg-habeas-navy/5 ring-1 ring-inset ring-habeas-navy/30',
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusLight tone={visual.light} pulse={visual.pulse} title={visual.state} />
        <span className="text-sm font-medium tabular-nums text-ink">
          {stagePercent(counts)}%
        </span>
        {counts.failed > 0 ? <Badge variant="fail">{formatCount(counts.failed)} failed</Badge> : null}
      </div>
      <p className="mt-0.5 text-[10px] tabular-nums text-mute">
        {formatCount(counts.success)} of {formatCount(counts.total)}
        {counts.inFlight > 0 ? ` · ${formatCount(counts.inFlight)} in flight` : ''}
      </p>
    </button>
  )
}

function cellBreakdown(counts: StageCounts): string {
  return `finished ${formatCount(counts.success)} · in flight ${formatCount(
    counts.inFlight,
  )} · queued ${formatCount(counts.open)} · failed ${formatCount(counts.failed)}`
}

export function VariantBMatrix() {
  const [selected, setSelected] = useState<CellRef | null>(null)
  const selectedVertical = selected
    ? LIVE_VERTICALS.find((row) => row.id === selected.verticalId)
    : undefined
  const selectedStage = selected
    ? PIPELINE_LIVE_STAGES.find((stage) => stage.id === selected.stage)
    : undefined

  return (
    <LabFrame title="B · Stage × vertical matrix">
      <div className="space-y-3">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-44">Vertical</TableHead>
              {PIPELINE_LIVE_STAGES.map((stage) => (
                <TableHead key={stage.id}>{stage.label}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {LIVE_VERTICALS.map((vertical) => (
              <TableRow key={vertical.id}>
                <TableCell>
                  <VerticalName vertical={vertical} />
                </TableCell>
                {PIPELINE_LIVE_STAGES.map((stage) => (
                  <TableCell key={stage.id} className="align-top">
                    <MatrixCell
                      vertical={vertical}
                      stage={stage.id}
                      selected={
                        selected?.verticalId === vertical.id && selected.stage === stage.id
                      }
                      onSelect={() => setSelected({ verticalId: vertical.id, stage: stage.id })}
                    />
                  </TableCell>
                ))}
              </TableRow>
            ))}
            {CATALOG_ONLY_VERTICALS.map((vertical) => (
              <TableRow key={vertical.id} className="opacity-60">
                <TableCell>
                  <VerticalName vertical={vertical} />
                </TableCell>
                <TableCell colSpan={PIPELINE_LIVE_STAGES.length}>
                  <span className="text-[11px] text-mute">
                    Catalog-only — matching is not live
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {selected && selectedVertical && selectedStage ? (
          <p className="rounded-md border border-line bg-canvas px-3 py-2 text-[11px] tabular-nums text-ink-soft">
            {selectedVertical.label} · {selectedStage.label}:{' '}
            {cellBreakdown(selectedVertical.stages[selected.stage])}
          </p>
        ) : (
          <p className="text-[11px] text-mute">
            Select a cell for its full state breakdown. Grey cells are not started.
          </p>
        )}
      </div>
    </LabFrame>
  )
}
