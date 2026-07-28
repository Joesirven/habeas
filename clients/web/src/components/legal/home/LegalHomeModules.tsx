import { Link } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { COARSE_STAGE_ORDER, stageLabel } from '@/lib/legalJourneyLabels'

type OperationsPulseProps = {
  pulse: LegalPortfolio['operations_pulse']
  onChipClick?: (chip: 'assigned' | 'team' | 'at_risk' | 'overdue') => void
}

export function OperationsPulse({ pulse, onChipClick }: OperationsPulseProps) {
  const chips = [
    { id: 'assigned' as const, label: 'Assigned to you', value: pulse.open_assigned_to_you },
    { id: 'team' as const, label: 'Open team-wide', value: pulse.open_team_wide },
    { id: 'at_risk' as const, label: 'SLA at risk', value: pulse.sla_at_risk },
    { id: 'overdue' as const, label: 'Overdue', value: pulse.overdue },
  ]
  return (
    <div className="flex flex-wrap gap-2">
      {chips.map((chip) => (
        <button
          key={chip.id}
          type="button"
          className="taste-frost-chip tabular-nums text-xs"
          onClick={() => onChipClick?.(chip.id)}
        >
          {chip.label}: {chip.value}
        </button>
      ))}
    </div>
  )
}

export type HomeWindow = '7' | '30' | '90' | 'ytd' | 'all'

type DateToolbarProps = {
  value: HomeWindow
  onChange: (next: HomeWindow) => void
}

const WINDOWS: { value: HomeWindow; label: string }[] = [
  { value: '7', label: '7d' },
  { value: '30', label: '30d' },
  { value: '90', label: '90d' },
  { value: 'ytd', label: 'YTD' },
  { value: 'all', label: 'All' },
]

export function DateToolbar({ value, onChange }: DateToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Analytics date range">
      {WINDOWS.map((window) => (
        <button
          key={window.value}
          type="button"
          className={value === window.value ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
          onClick={() => onChange(window.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              onChange(window.value)
            }
          }}
        >
          {window.label}
        </button>
      ))}
    </div>
  )
}

type FulfillmentBatchListProps = {
  batches: LegalPortfolio['fulfillment_batches']
  selectedKey: string | null
  onSelect: (batchKey: string | null) => void
}

export function FulfillmentBatchList({
  batches,
  selectedKey,
  onSelect,
}: FulfillmentBatchListProps) {
  if (batches.length === 0) {
    return <p className="text-xs text-mute">No intake batches in this window.</p>
  }
  return (
    <div className="space-y-2">
      <ul className="divide-y divide-line/60 text-xs">
        {batches.map((batch) => (
          <li key={batch.batch_key}>
            <button
              type="button"
              className={`flex w-full items-center justify-between py-2 text-left ${
                selectedKey === batch.batch_key ? 'font-medium text-ink' : 'text-ink-soft'
              }`}
              onClick={() =>
                onSelect(selectedKey === batch.batch_key ? null : batch.batch_key)
              }
            >
              <span>
                {batch.source_label} · {new Date(batch.received_at).toLocaleString()}
              </span>
              <span className="tabular-nums">{batch.request_count}</span>
            </button>
          </li>
        ))}
      </ul>
      <Link to="/requests" className="text-xs text-habeas-navy hover:underline">
        See all
      </Link>
    </div>
  )
}

type PipelineFunnelProps = {
  stages: LegalPortfolio['stage_reach_counts']
  onStageClick?: (stage: string) => void
}

export function PipelineFunnel({ stages, onStageClick }: PipelineFunnelProps) {
  const byStage = new Map(stages.map((row) => [row.stage, row.reached_count]))
  const max = Math.max(1, ...COARSE_STAGE_ORDER.map((key) => byStage.get(key) ?? 0))
  return (
    <div className="flex items-end gap-2" style={{ minHeight: '8rem' }}>
      {COARSE_STAGE_ORDER.map((stage) => {
        const count = byStage.get(stage) ?? 0
        const height = `${Math.max((count / max) * 100, count > 0 ? 10 : 0)}%`
        return (
          <button
            key={stage}
            type="button"
            className="flex min-w-0 flex-1 flex-col items-center gap-1"
            onClick={() => onStageClick?.(stage)}
          >
            <span className="text-[0.65rem] tabular-nums text-mute">{count}</span>
            <div className="flex h-24 w-full items-end">
              <div className="w-full rounded-t bg-habeas-navy/75" style={{ height }} />
            </div>
            <span className="text-center text-[0.6rem] leading-tight text-ink-soft">
              {stageLabel(stage)}
            </span>
          </button>
        )
      })}
    </div>
  )
}

type HeatmapProps = {
  cells: LegalPortfolio['heatmap_cells']
}

export function OpenRequestsHeatmap({ cells }: HeatmapProps) {
  const sources = [...new Set(cells.map((c) => c.intake_source))]
  const types = [...new Set(cells.map((c) => c.request_type))]
  const lookup = new Map(cells.map((c) => [`${c.intake_source}:${c.request_type}`, c.count]))
  return (
    <div className="overflow-x-auto text-xs">
      <table className="min-w-full">
        <thead>
          <tr>
            <th className="p-1 text-left text-mute">Source</th>
            {types.map((type) => (
              <th key={type} className="p-1 text-mute">
                {type}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sources.map((source) => (
            <tr key={source} className="border-t border-line/50">
              <td className="p-1 text-ink-soft">{source}</td>
              {types.map((type) => (
                <td key={type} className="p-1 tabular-nums">
                  <Link
                    to="/requests"
                    search={{ source: source as 'drop', request_type: type }}
                    className="hover:underline"
                  >
                    {lookup.get(`${source}:${type}`) ?? 0}
                  </Link>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

type DeadlineRiskBandProps = {
  risk: LegalPortfolio['deadline_risk']
}

export function DeadlineRiskBand({ risk }: DeadlineRiskBandProps) {
  const total = risk.overdue + risk.due_within_7_days + risk.on_track || 1
  const segments = [
    { key: 'overdue', count: risk.overdue, className: 'bg-red-500' },
    { key: 'due7', count: risk.due_within_7_days, className: 'bg-amber-400' },
    { key: 'on_track', count: risk.on_track, className: 'bg-emerald-500' },
  ]
  return (
    <div className="space-y-2">
      <div className="flex h-2 overflow-hidden rounded-full bg-line/40">
        {segments.map((segment) => (
          <div
            key={segment.key}
            className={segment.className}
            style={{ width: `${(segment.count / total) * 100}%` }}
            title={`${segment.key}: ${segment.count}`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-ink-soft">
        <span>Overdue: {risk.overdue}</span>
        <span>Due ≤7d: {risk.due_within_7_days}</span>
        <span>On track: {risk.on_track}</span>
        <span className="taste-frost-chip">Closed YTD: {risk.closed_ytd}</span>
      </div>
    </div>
  )
}

type DataOwnerQueuesProps = {
  queues: LegalPortfolio['data_owner_queues']
}

export function DataOwnerQueues({ queues }: DataOwnerQueuesProps) {
  const top = queues.slice(0, 5)
  return (
    <ul className="space-y-2 text-xs">
      {top.map((row) => (
        <li key={row.assignee_identity ?? 'unassigned'} className="flex justify-between gap-2">
          <span className="font-mono text-ink">{row.assignee_identity ?? 'Unassigned'}</span>
          <span className="tabular-nums text-ink-soft">{row.pending_count} pending</span>
        </li>
      ))}
    </ul>
  )
}
