import type { ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

import {
  MATCH_QUALITY_FIXTURE,
  MATCH_QUALITY_PARAMETERS,
  formatCount,
  formatRate,
  type ParameterRow,
} from './fixture'

export function LabFrame({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <article className="rounded-md border border-line bg-white">
      <header className="border-b border-line px-4 py-3">
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
          Fixture · {MATCH_QUALITY_FIXTURE.snapshotDate} · counts only
        </p>
        <h2 className="mt-1 text-sm font-semibold text-ink">{title}</h2>
        <p className="mt-0.5 text-[11px] text-mute">
          Source CA DROP · all CA · all delete · {formatCount(MATCH_QUALITY_FIXTURE.totalRequests)}{' '}
          requests
        </p>
      </header>
      <div className="p-4">{children}</div>
    </article>
  )
}

export function StatusBadge({ row }: { row: ParameterRow }) {
  if (row.breach) {
    return <Badge variant="fail">Breach</Badge>
  }
  return <Badge variant="ok">Healthy</Badge>
}

export function DenseRateTable({
  dualRunning = false,
}: {
  dualRunning?: boolean
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Parameter</TableHead>
          <TableHead className="text-right">Requests</TableHead>
          {dualRunning ? (
            <>
              <TableHead className="text-right">Batch exact</TableHead>
              <TableHead className="text-right">Running exact</TableHead>
              <TableHead className="text-right">Batch any-hit</TableHead>
              <TableHead className="text-right">Running any-hit</TableHead>
            </>
          ) : (
            <>
              <TableHead className="text-right">Exact</TableHead>
              <TableHead className="text-right">Exact %</TableHead>
              <TableHead className="text-right">Any-hit</TableHead>
              <TableHead className="text-right">Any-hit %</TableHead>
              <TableHead className="text-right">Multi</TableHead>
              <TableHead className="text-right">Multi %</TableHead>
            </>
          )}
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {MATCH_QUALITY_PARAMETERS.map((row) => (
          <TableRow key={row.id}>
            <TableCell className="font-medium text-ink">{row.label}</TableCell>
            <TableCell className="text-right tabular-nums">
              {formatCount(row.requests)}
            </TableCell>
            {dualRunning ? (
              <>
                <TableCell className="text-right tabular-nums">
                  {formatCount(row.exact)} · {formatRate(row.exact, row.requests)}
                </TableCell>
                <TableCell className="text-right tabular-nums text-ink-soft">
                  {formatCount(row.exact)} · {formatRate(row.exact, row.requests)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatCount(row.anyHit)} · {formatRate(row.anyHit, row.requests)}
                </TableCell>
                <TableCell className="text-right tabular-nums text-ink-soft">
                  {formatCount(row.anyHit)} · {formatRate(row.anyHit, row.requests)}
                </TableCell>
              </>
            ) : (
              <>
                <TableCell className="text-right tabular-nums">
                  {formatCount(row.exact)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatRate(row.exact, row.requests)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatCount(row.anyHit)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatRate(row.anyHit, row.requests)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatCount(row.multi)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatRate(row.multi, row.requests)}
                </TableCell>
              </>
            )}
            <TableCell>
              <StatusBadge row={row} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
