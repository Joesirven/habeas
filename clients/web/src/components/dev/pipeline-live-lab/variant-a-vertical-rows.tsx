import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

import {
  LIVE_VERTICALS,
  formatCount,
  formatPercent,
  microBarTone,
  stagePercent,
  stageVisual,
  type PipelineLiveStageId,
} from './fixture'
import {
  CatalogOnlySection,
  FailedCount,
  LabFrame,
  MicroBar,
  StageSwitcher,
  StatusLight,
  VerticalName,
} from './chrome'

export function VariantAVerticalRows() {
  const [stage, setStage] = useState<PipelineLiveStageId>('matching')
  const reviewMode = stage === 'review'

  return (
    <LabFrame title="A · Vertical rows under the selected stage">
      <div className="space-y-3">
        <StageSwitcher stage={stage} onSelect={setStage} />

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Vertical</TableHead>
              <TableHead className="text-right">
                {reviewMode ? 'Resolved' : 'Finished'}
              </TableHead>
              <TableHead className="text-right">In flight</TableHead>
              <TableHead className="text-right">{reviewMode ? 'Open' : 'Queued'}</TableHead>
              <TableHead className="text-right">Failed</TableHead>
              <TableHead className="text-right">%</TableHead>
              <TableHead className="w-40">Progress</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {LIVE_VERTICALS.map((vertical) => {
              const counts = vertical.stages[stage]
              const visual = stageVisual(counts)
              const percent = stagePercent(counts)
              return (
                <TableRow key={vertical.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <StatusLight tone={visual.light} pulse={visual.pulse} title={visual.state} />
                      <Link
                        to="/ops/runs"
                        className="min-w-0 rounded-sm underline-offset-2 hover:underline"
                        title={`Runs for this batch · ${vertical.label}`}
                      >
                        <VerticalName vertical={vertical} />
                      </Link>
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatCount(counts.success)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatCount(counts.inFlight)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatCount(counts.open)}
                  </TableCell>
                  <TableCell className="text-right">
                    <FailedCount count={counts.failed} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatPercent(counts)}
                  </TableCell>
                  <TableCell>
                    <MicroBar
                      percent={percent}
                      tone={microBarTone(visual)}
                      shimmer={counts.inFlight > 0}
                    />
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>

        <p className="text-[11px] leading-relaxed text-mute">
          Row order is catalog order — rows never re-sort while counters tick.
          {reviewMode
            ? ' Review grain: Resolved = decided, Open = needs review.'
            : ' Queued = open work items not yet claimed.'}
        </p>

        <CatalogOnlySection />
      </div>
    </LabFrame>
  )
}
