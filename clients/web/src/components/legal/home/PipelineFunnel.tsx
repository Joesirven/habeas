import { Link } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { COARSE_STAGE_ORDER, stageLabel } from '@/lib/legalJourneyLabels'
import { cn } from '@/lib/utils'

type SelectedBatch = NonNullable<LegalPortfolio['fulfillment_batches']>[number]

type PipelineFunnelProps = {
  stages: NonNullable<LegalPortfolio['stage_reach_counts']>
  selectedBatch?: SelectedBatch | null
  onClearBatch?: () => void
  onStageClick?: (stage: string) => void
}

const COLUMN_HEIGHT_PX = 92

function capPercent(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 0
  return Math.min(100, Math.round(value))
}

function formatReceivedAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function PipelineFunnel({
  stages,
  selectedBatch,
  onClearBatch,
  onStageClick,
}: PipelineFunnelProps) {
  const byStage = new Map(stages.map((row) => [row.stage, row]))
  const ordered = COARSE_STAGE_ORDER.map((key) => {
    const row = byStage.get(key)
    return {
      stage: key,
      reached: row?.reached_count ?? 0,
      dropped: row?.dropped_count ?? 0,
    }
  })
  const topCount = Math.max(ordered[0]?.reached ?? 0, 1)

  return (
    <div className="space-y-3" role="img" aria-label="Pipeline stage reach funnel">
      {selectedBatch ? (
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-soft">
          <span>
            Scoped to batch: {selectedBatch.source_label} · received{' '}
            {formatReceivedAt(selectedBatch.received_at)} ·{' '}
            {selectedBatch.request_count.toLocaleString()} requests
          </span>
          {onClearBatch ? (
            <button
              type="button"
              className="rounded-full border border-line bg-panel px-2 py-0.5 text-[0.65rem] font-medium text-ink-soft transition-colors hover:border-habeas-navy/35 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid"
              onClick={onClearBatch}
            >
              All batches ✕
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="flex items-end gap-2">
        {ordered.map((row, index) => {
          const previousReached = index === 0 ? row.reached : ordered[index - 1]!.reached
          const ofTopPct = capPercent((row.reached / topCount) * 100)
          const ofPrevPct =
            index === 0 ? 100 : capPercent((row.reached / Math.max(previousReached, 1)) * 100)
          const dropCount = index === 0 ? 0 : Math.max(0, previousReached - row.reached)
          const dropPct = index === 0 ? 0 : capPercent((dropCount / Math.max(previousReached, 1)) * 100)

          return (
            <Link
              key={row.stage}
              to="/requests"
              search={{ stage: row.stage }}
              className="group flex min-w-0 flex-1 flex-col gap-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid"
              title={`Reached ${stageLabel(row.stage)}: ${row.reached.toLocaleString()}`}
              onClick={(event) => {
                if (onStageClick) {
                  event.preventDefault()
                  onStageClick(row.stage)
                }
              }}
            >
              <span className="truncate text-[0.65rem] text-mute">{stageLabel(row.stage)}</span>
              <span className="text-sm font-semibold tabular-nums text-ink">
                {row.reached.toLocaleString()}
              </span>
              <div
                className="flex w-full flex-col justify-end gap-0.5"
                style={{ height: COLUMN_HEIGHT_PX }}
              >
                {dropPct > 0 ? (
                  <div
                    className="w-full rounded-sm bg-line/70"
                    style={{ height: Math.max(4, (dropPct / 100) * COLUMN_HEIGHT_PX) }}
                    title={`Dropped before ${stageLabel(row.stage)}: ${dropCount.toLocaleString()} (−${dropPct}% from previous)`}
                  />
                ) : null}
                <div
                  className={cn(
                    'w-full rounded-sm bg-habeas-navy transition-opacity group-hover:opacity-90',
                    row.reached === 0 && 'opacity-25',
                  )}
                  style={{ height: Math.max(6, (ofTopPct / 100) * COLUMN_HEIGHT_PX) }}
                  title={`Reached ${stageLabel(row.stage)}: ${row.reached.toLocaleString()} (${ofTopPct}% of received)`}
                />
              </div>
              <span className="text-[0.65rem] tabular-nums text-ink-soft">
                {ofTopPct}%
                {index > 0 ? ` · ${ofPrevPct}% of prev` : ''}
              </span>
            </Link>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.65rem] text-mute">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-habeas-navy" />
          Reached stage
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-line/80" />
          Dropped before step
        </span>
        <span>
          {selectedBatch
            ? 'Cumulative reach per stage in the selected batch · % of batch received'
            : 'Cumulative reach per stage across all batches · % of received'}{' '}
          · click a column for the cohort list
        </span>
      </div>
    </div>
  )
}
