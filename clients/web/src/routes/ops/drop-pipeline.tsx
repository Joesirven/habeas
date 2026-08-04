import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { Fragment, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { Skeleton, SkeletonLines } from '@/components/AppShell'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { actionToast } from '@/lib/action-toast'
import { RoleGate, isSuperAdmin } from '@/lib/auth'
import { cn } from '@/lib/utils'
import {
  getDropBulkProcess,
  getDropPipeline,
  getDropWorkerTrends,
  listDropBulkProcesses,
  listDropBulkProcessRuns,
  listOpsLogs,
  listRuns,
  postDropDownload,
  postDropFulfill,
  postDropLand,
  postDropPromote,
  postHashIndexRefreshEnqueue,
  postHashIndexRefreshEnqueueAll,
  postHashIndexRefreshProcess,
  type BulkProcessDetail,
  type BulkProcessRunGroup,
  type BulkProcessStageCounts,
  type BulkProcessSummary,
  type BulkProcessesPayload,
  type DropPipelineStatus,
  type HashIndexRefreshStatus,
  type OpsLogEntry,
  type OpsLogSeverity,
  type OpsTimeWindow,
  type WorkerHealthProbe,
} from '@/lib/api'
import {
  runsSearchForBulkStage,
  runsSearchForWorker,
  type BulkStageRunState,
  type PipelineStageTab,
  type PipelineTab,
} from '@/router'

function PlayPipelineIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 8.5v7l6-3.5-6-3.5z" fill="currentColor" />
    </svg>
  )
}

const WORKER_ORDER = [
  'drop_connector',
  'drop_ingestor',
  'request_dispatcher',
  'matching',
  'data_fulfillment',
  'hash_index_refresh',
  'reaper',
  'intake_drop_poller',
] as const

const PIPELINE_TAB_BAR: { key: PipelineTab; label: string }[] = [
  { key: 'pipeline', label: 'Pipeline' },
  { key: 'hash_refresh', label: 'Hash refresh' },
  { key: 'history', label: 'History' },
  { key: 'errors', label: 'Errors' },
  { key: 'logs', label: 'Logs' },
]

type BulkPipelineStageKey = keyof BulkProcessDetail['stages']

const BULK_CARD_STAGE_TABS: {
  key: PipelineStageTab
  label: string
  runStage: string
  stages: { key: BulkPipelineStageKey; label: string }[]
}[] = [
  {
    key: 'download',
    label: 'Download',
    runStage: 'download',
    stages: [{ key: 'download', label: 'Download' }],
  },
  {
    key: 'ingest',
    label: 'Ingest',
    runStage: 'land,promote',
    stages: [
      { key: 'land', label: 'Land' },
      { key: 'promote', label: 'Promote' },
    ],
  },
  {
    key: 'matching',
    label: 'Matching',
    runStage: 'matching',
    stages: [{ key: 'matching', label: 'Matching' }],
  },
  {
    key: 'review',
    label: 'Review',
    runStage: 'matching',
    stages: [{ key: 'review', label: 'Review' }],
  },
  {
    key: 'fulfillment',
    label: 'Fulfillment',
    runStage: 'matching',
    stages: [{ key: 'fulfillment', label: 'Fulfillment' }],
  },
]

function mergeStageCounts(
  parts: (BulkProcessStageCounts | undefined)[],
): BulkProcessStageCounts {
  const merged: BulkProcessStageCounts = {
    total: 0,
    open: 0,
    success: 0,
    failed: 0,
    other: 0,
    by_list_type: [],
  }
  for (const part of parts) {
    if (!part) continue
    merged.total += part.total
    merged.open += part.open
    merged.success += part.success
    merged.failed += part.failed
    merged.other = (merged.other ?? 0) + (part.other ?? 0)
    if (part.by_list_type?.length) {
      merged.by_list_type = [...(merged.by_list_type ?? []), ...part.by_list_type]
    }
  }
  return merged
}

function countsForStageTab(
  detail: BulkProcessDetail | undefined,
  tab: (typeof BULK_CARD_STAGE_TABS)[number],
): BulkProcessStageCounts | undefined {
  if (!detail) return undefined
  // Matching % / Finished·Queued·Failed chips use matching_attempts only.
  // Review is its own tab with request-spine counts from detail.stages.review.
  if (tab.key === 'matching') {
    return detail.stages.matching
  }
  if (tab.key === 'review') {
    return detail.stages.review
  }
  // Ingest: land + promote are sequential CSV steps — merged success/total is a fair
  // average across both sub-stages.
  return mergeStageCounts(tab.stages.map((stage) => detail.stages[stage.key]))
}

function isStageTabCurrent(
  detail: BulkProcessDetail | undefined,
  tab: (typeof BULK_CARD_STAGE_TABS)[number],
): boolean {
  if (!detail) return false
  return tab.stages.some((stage) => detail.overall.current_stage === stage.key)
}

const RUN_STATUS_FILTERS: { value: string; label: string }[] = [
  { value: 'attention', label: 'Open & failed' },
  { value: 'pending', label: 'Queued' },
  { value: 'fail', label: 'Failed' },
  { value: 'abandoned', label: 'Abandoned' },
  { value: 'success', label: 'Finished' },
  { value: '', label: 'All' },
]

function stageCountsBlurb(stage: BulkProcessStageCounts | undefined): string {
  if (!stage) return '—'
  return `${stage.success}/${stage.total} ok · ${stage.open} open · ${stage.failed} failed`
}

type StageVisual = 'complete' | 'active' | 'failed' | 'pending' | 'idle'

function stageVisualState(
  counts: BulkProcessStageCounts | undefined,
  isCurrent: boolean,
): StageVisual {
  if (!counts || counts.total === 0) return isCurrent ? 'active' : 'idle'
  if (counts.failed > 0) return 'failed'
  const done =
    counts.open === 0 && counts.success >= counts.total && counts.total > 0
  if (done) return 'complete'
  if (counts.open > 0 || counts.success < counts.total) {
    return isCurrent ? 'active' : 'pending'
  }
  return isCurrent ? 'active' : 'idle'
}

function stageStripTone(visual: StageVisual): {
  text: string
  light: 'emerald' | 'sky' | 'amber' | 'red' | 'mute' | 'navy'
  bar: string
  wash: string
} {
  switch (visual) {
    case 'complete':
      return {
        text: 'text-emerald-900',
        light: 'emerald',
        bar: 'bg-emerald-600',
        wash: 'bg-emerald-50/80',
      }
    case 'active':
      return {
        text: 'text-habeas-navy',
        light: 'emerald',
        bar: 'bg-emerald-600',
        wash: 'bg-emerald-50/50',
      }
    case 'failed':
      return {
        text: 'text-red-800',
        light: 'red',
        bar: 'bg-red-600',
        wash: 'bg-red-50/70',
      }
    case 'pending':
      return {
        text: 'text-amber-950',
        light: 'amber',
        bar: 'bg-amber-500',
        wash: 'bg-amber-50/60',
      }
    default:
      return {
        text: 'text-ink-soft',
        light: 'mute',
        bar: 'bg-habeas-navy/40',
        wash: 'bg-transparent',
      }
  }
}

const SERVED_STATE_ACRONYMS = [
  'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA',
  'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM',
  'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA',
  'WV', 'WI', 'WY',
] as const

const ACTIONS = [
  { key: 'download', label: 'Download ZIP', run: () => postDropDownload() },
  { key: 'land', label: 'Land (unzip)', run: () => postDropLand() },
  { key: 'promote', label: 'Promote to raw', run: () => postDropPromote() },
  { key: 'fulfill', label: 'Fulfill', run: () => postDropFulfill() },
] as const

type ActionKey = (typeof ACTIONS)[number]['key']

const DROP_PIPELINE_RUN_TOAST_ID = 'drop-pipeline-run'
const DROP_HASH_REFRESH_TOAST_ID = 'drop-hash-refresh'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function summarizeActionPayload(raw: string | null): { status: string | null; blurb: string } {
  if (!raw) return { status: null, blurb: '' }
  if (raw === '__pending__') {
    return { status: 'queued', blurb: 'Waiting on worker response…' }
  }
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const status = typeof parsed.status === 'string' ? parsed.status : null
    const parts: string[] = []
    if (Array.isArray(parsed.lists)) parts.push(`${parsed.lists.length} lists`)
    if (Array.isArray(parsed.land_attempt_ids)) {
      parts.push(`${parsed.land_attempt_ids.length} land attempts`)
    }
    if (typeof parsed.connector_attempt_id === 'number') {
      parts.push(`connector #${parsed.connector_attempt_id}`)
    }
    if (typeof parsed.attempt_id === 'number') parts.push(`attempt #${parsed.attempt_id}`)
    if (typeof parsed.process_id === 'number') parts.push(`process #${parsed.process_id}`)
    if (typeof parsed.request_id === 'string') parts.push(`request ${parsed.request_id.slice(0, 8)}…`)
    if (typeof parsed.match_count === 'number') parts.push(`${parsed.match_count} matches`)
    if (typeof parsed.dispatched === 'number') parts.push(`${parsed.dispatched} dispatched`)
    if (typeof parsed.gcs_uri === 'string') {
      const leaf = parsed.gcs_uri.split('/').pop() ?? parsed.gcs_uri
      parts.push(leaf)
    }
    const blurb =
      parts.join(' · ') ||
      (status === 'ok' ? 'Run accepted' : status ? status : 'Payload ready')
    return { status: status ?? (parts.length ? 'ok' : null), blurb }
  } catch {
    const trimmed = raw.trim()
    return {
      status: null,
      blurb: trimmed.length > 72 ? `${trimmed.slice(0, 72)}…` : trimmed,
    }
  }
}

function ActionResultFrame({
  lastAction,
  actionResult,
  onClear,
}: {
  lastAction: string | null
  actionResult: string | null
  onClear: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const titleId = useId()
  const pending = actionResult === '__pending__'
  const { status, blurb } = summarizeActionPayload(actionResult)
  const isError =
    !pending &&
    (status === 'error' ||
      (actionResult != null &&
        !actionResult.trimStart().startsWith('{') &&
        /error|fail|502|503|401|403/i.test(actionResult)))

  if (!lastAction && !actionResult) return null

  const statusClass = isError
    ? 'text-red-700'
    : pending || status === 'queued'
      ? 'text-habeas-navy'
      : 'text-emerald-700'

  return (
    <>
      <div
        className={
          pending
            ? 'min-w-0 rounded-md border border-sky-200 bg-sky-50/90'
            : 'min-w-0 rounded-md border border-line bg-paper-raised/80'
        }
      >
        <div className="flex items-start justify-between gap-3 border-b border-line/80 px-3 py-2.5">
          <div className="min-w-0">
            <Micro>{pending ? 'Run queued' : 'Last response'}</Micro>
            <p className="mt-1 truncate text-sm text-ink">{lastAction ?? 'Action'}</p>
            <p className="mt-0.5 truncate text-xs text-ink-soft">
              {status ? <span className={statusClass}>{status}</span> : null}
              {status && blurb ? <span className="text-mute"> · </span> : null}
              {blurb || '—'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {!pending ? (
              <button
                type="button"
                className="taste-btn px-2.5 py-1 text-[0.65rem]"
                onClick={() => setExpanded(true)}
              >
                View payload
              </button>
            ) : null}
            <button
              type="button"
              className="taste-btn px-2.5 py-1 text-[0.65rem]"
              onClick={onClear}
              aria-label="Clear last response"
            >
              Clear
            </button>
          </div>
        </div>
        {!pending ? (
          <pre className="max-h-28 overflow-auto overscroll-contain px-3 py-2 font-mono text-[0.7rem] leading-relaxed text-ink-soft [overflow-wrap:anywhere] whitespace-pre-wrap break-all">
            {actionResult ?? ''}
          </pre>
        ) : null}
      </div>

      {expanded
        ? createPortal(
          <div
            className="fixed inset-0 z-[100] flex items-end justify-center bg-habeas-navy/45 p-4 backdrop-blur-sm sm:items-center"
            role="presentation"
            onClick={() => setExpanded(false)}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby={titleId}
              className="taste-panel flex max-h-[min(85vh,40rem)] w-full max-w-2xl flex-col overflow-hidden p-0"
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  event.preventDefault()
                  setExpanded(false)
                }
              }}
            >
              <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
                <div className="min-w-0">
                  <Micro>Payload</Micro>
                  <h3
                    id={titleId}
                    className="mt-2 truncate font-display text-xl font-medium tracking-tight text-ink"
                  >
                    {lastAction ?? 'Action response'}
                  </h3>
                </div>
                <button
                  type="button"
                  className="taste-btn shrink-0 px-2.5 py-1 text-[0.65rem]"
                  onClick={() => setExpanded(false)}
                >
                  Close
                </button>
              </div>
              <pre className="min-h-0 flex-1 overflow-auto overscroll-contain px-5 py-4 font-mono text-xs leading-relaxed text-ink-soft [overflow-wrap:anywhere] whitespace-pre-wrap break-all">
                {actionResult ?? ''}
              </pre>
            </div>
          </div>,
          document.body,
        )
        : null}
    </>
  )
}

function PipelineTabBar({
  active,
  onSelect,
}: {
  active: PipelineTab
  onSelect: (tab: PipelineTab) => void
}) {
  return (
    <div
      role="tablist"
      aria-label="DROP pipeline"
      className="flex gap-0 overflow-x-auto border-b border-line"
    >
      {PIPELINE_TAB_BAR.map((tab) => {
        const selected = active === tab.key
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={selected}
            className={
              selected
                ? 'relative shrink-0 px-3.5 py-2.5 text-xs font-medium text-habeas-navy after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:rounded-full after:bg-habeas-navy'
                : 'shrink-0 px-3.5 py-2.5 text-xs font-medium text-mute transition-colors hover:text-ink'
            }
            onClick={() => onSelect(tab.key)}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}

function runAgeLabel(startedAt: string): string {
  const ms = Date.now() - new Date(startedAt).getTime()
  if (Number.isNaN(ms) || ms < 0) return '—'
  const minutes = Math.floor(ms / 60_000)
  if (minutes < 60) return `${Math.max(minutes, 0)}m`
  const hours = Math.floor(minutes / 60)
  const rem = minutes % 60
  return rem > 0 ? `${hours}h ${rem}m` : `${hours}h`
}

const OPEN_RUN_STATUSES = new Set(['pending', 'claimed', 'in_flight', 'leased'])
const FAILED_RUN_STATUSES = new Set([
  'submit_error',
  'outcome_error',
  'timeout',
  'abandoned',
])

/** Shared by bulk-card toggles and Individual view (RUN_STATUS_FILTERS values). */
function runMatchesStatusFilter(
  run: { status: string },
  statusFilter: string,
): boolean {
  const s = run.status.toLowerCase()
  if (!statusFilter) return true
  if (statusFilter === 'attention') {
    return (
      s.includes('fail') ||
      s.includes('error') ||
      OPEN_RUN_STATUSES.has(s) ||
      s === 'abandoned'
    )
  }
  if (statusFilter === 'abandoned') return s === 'abandoned'
  if (statusFilter === 'pending') return OPEN_RUN_STATUSES.has(s)
  if (statusFilter === 'fail') {
    return (
      (s.includes('fail') || s.includes('error') || s === 'timeout') &&
      s !== 'abandoned'
    )
  }
  if (statusFilter === 'success') return s === 'success'
  // Legacy CompactFilterSelect aliases used by standalone ProcessRunsHistoryPanel
  if (statusFilter === 'open') return OPEN_RUN_STATUSES.has(s)
  if (statusFilter === 'failed') return FAILED_RUN_STATUSES.has(s)
  return s.includes(statusFilter.toLowerCase())
}

function filterRunGroupsForStatus(
  groups: BulkProcessRunGroup[],
  statusFilter: string,
): BulkProcessRunGroup[] {
  return groups
    .map((group) => {
      const runs = group.runs.filter((run) =>
        runMatchesStatusFilter(run, statusFilter),
      )
      return { ...group, runs, run_count: runs.length }
    })
    .filter((group) => group.run_count > 0)
}

function CompactFilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const selected = options.find((option) => option.value === value)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 gap-1 px-2 text-[0.65rem] font-normal"
          aria-label={label}
        >
          <span className="text-mute">{label}</span>
          <span className="max-w-[7rem] truncate text-ink">
            {selected?.label ?? 'Any'}
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-44 p-1" align="start">
        <ul className="max-h-56 overflow-y-auto">
          {options.map((option) => {
            const active = option.value === value
            return (
              <li key={option.value || '__any'}>
                <button
                  type="button"
                  className={cn(
                    'flex w-full rounded px-2 py-1.5 text-left text-[0.7rem]',
                    active
                      ? 'bg-habeas-navy/10 font-medium text-habeas-navy'
                      : 'text-ink hover:bg-panel/60',
                  )}
                  onClick={() => {
                    onChange(option.value)
                    setOpen(false)
                  }}
                >
                  {option.label}
                </button>
              </li>
            )
          })}
        </ul>
      </PopoverContent>
    </Popover>
  )
}

function ProcessRunsHistoryPanel({
  stage,
  processId,
  processIds,
  days = 1,
  emptyLabel,
  defaultStatus = 'attention',
  title = 'Open & failed runs',
  embedded = false,
  hideStatusFilter = false,
}: {
  stage: string
  processId?: number
  /** When set, only groups whose process_id is in this set are shown. */
  processIds?: number[]
  days?: number
  emptyLabel: string
  /** Default: attention (open + failed) so blockers surface immediately. */
  defaultStatus?: string
  title?: string
  /** Drop outer chrome when nested in Request Processing Pipeline. */
  embedded?: boolean
  hideStatusFilter?: boolean
}) {
  const [statusFilter, setStatusFilter] = useState<string>(defaultStatus)
  useEffect(() => {
    setStatusFilter(defaultStatus)
  }, [defaultStatus])
  const runsQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'drop-process-runs',
      stage,
      processId ?? 'all',
      days,
    ],
    queryFn: () =>
      // Fetch unfiltered; apply RUN_STATUS_FILTERS (and legacy aliases) client-side
      // so fail/pending/attention match the bulk-card toggle semantics.
      listDropBulkProcessRuns({
        stage,
        days,
        process_id: processId,
      }),
    refetchInterval: 5_000,
    placeholderData: (previous) => previous,
  })

  const allowed =
    processIds != null ? new Set(processIds) : null
  const groups = filterRunGroupsForStatus(
    runsQuery.data?.groups ?? [],
    statusFilter,
  ).filter((group) => {
    if (group.run_count <= 0) return false
    if (allowed != null && !allowed.has(group.process_id)) return false
    return true
  })
  const totalRuns = groups.reduce((sum, group) => sum + group.run_count, 0)

  const body =
    runsQuery.isError ? (
      <p className="px-3 py-3 text-xs text-red-700">Could not load process run history.</p>
    ) : runsQuery.isPending && !runsQuery.data ? (
      <div className="p-3">
        <SkeletonLines lines={3} />
      </div>
    ) : groups.length === 0 ? (
      <p className="px-3 py-3 text-xs text-ink-soft">{emptyLabel}</p>
    ) : (
      <div className="divide-y divide-line">
        {groups.map((group: BulkProcessRunGroup) => (
          <div key={group.process_id} className="px-3 py-2.5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-xs font-medium text-ink">{group.label}</p>
              <p className="text-[0.65rem] text-mute">
                {group.download_status} · {group.run_count} runs
              </p>
            </div>
            {group.runs.length === 0 ? (
              <p className="mt-1 text-[0.65rem] text-ink-soft">No runs for this filter.</p>
            ) : (
              <div className="mt-2 overflow-x-auto">
                <table className="taste-table">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Step</th>
                      <th>Status</th>
                      <th>Age</th>
                      <th>Attempt</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.runs.map((run) => (
                      <tr key={run.run_id}>
                        <td className="max-w-[9rem] truncate font-mono text-xs">
                          <Link
                            to="/ops/runs/$job/$attemptId"
                            params={{
                              job: run.job,
                              attemptId: String(run.attempt_id),
                            }}
                            className="text-habeas-mid underline decoration-habeas-mid/30 underline-offset-2"
                          >
                            {run.run_id}
                          </Link>
                        </td>
                        <td className="font-mono text-xs">{run.step}</td>
                        <td className="text-xs">{run.status.replaceAll('_', ' ')}</td>
                        <td className="tabular-nums text-xs text-ink-soft">
                          {run.started_at ? runAgeLabel(run.started_at) : '—'}
                        </td>
                        <td className="tabular-nums text-xs">{run.attempt_number}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
      </div>
    )

  if (embedded) {
    return (
      <div>
        {!hideStatusFilter || totalRuns > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-1.5">
            <span className="text-[0.65rem] tabular-nums text-mute">
              {groups.length} processes · {totalRuns} runs
            </span>
            {!hideStatusFilter ? (
              <CompactFilterSelect
                label="Runs"
                value={statusFilter}
                onChange={setStatusFilter}
                options={[
                  { value: 'attention', label: 'Open & failed' },
                  { value: 'open', label: 'Open' },
                  { value: 'failed', label: 'Failed' },
                  { value: 'success', label: 'Success' },
                  { value: '', label: 'All statuses' },
                ]}
              />
            ) : null}
          </div>
        ) : null}
        {body}
      </div>
    )
  }

  return (
    <div className="rounded-md border border-line bg-paper">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-1.5">
        <Micro>{title}</Micro>
        <div className="flex flex-wrap items-center gap-2">
          <CompactFilterSelect
            label="Runs"
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: 'attention', label: 'Open & failed' },
              { value: 'open', label: 'Open' },
              { value: 'failed', label: 'Failed' },
              { value: 'success', label: 'Success' },
              { value: '', label: 'All statuses' },
            ]}
          />
          <span className="text-[0.65rem] tabular-nums text-mute">
            {groups.length} processes · {totalRuns} runs
          </span>
        </div>
      </div>
      {body}
    </div>
  )
}

const LOG_WINDOW_OPTIONS: { value: OpsTimeWindow; label: string }[] = [
  { value: '8h', label: '8h' },
  { value: '24h', label: '24h' },
  { value: '1w', label: '1w' },
  { value: '3m', label: '3m' },
]

const LOG_RESOURCE_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'All resources' },
  { value: 'drop_connector', label: 'drop_connector' },
  { value: 'drop_ingestor', label: 'drop_ingestor' },
  { value: 'matching', label: 'matching' },
  { value: 'hash_index_refresh', label: 'hash_index_refresh' },
  { value: 'data_fulfillment', label: 'data_fulfillment' },
  { value: 'admin-api', label: 'admin-api' },
  { value: 'cli', label: 'cli' },
]

const LOG_SEVERITY_OPTIONS: OpsLogSeverity[] = ['ERROR', 'WARNING', 'INFO']

function severityBadgeClass(severity: OpsLogSeverity): string {
  if (severity === 'ERROR') return 'border-red-300/80 bg-red-50 text-red-800'
  if (severity === 'WARNING') return 'border-amber-300/80 bg-amber-50 text-amber-900'
  return 'border-line bg-paper text-ink-soft'
}

function formatLogTimestamp(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value || '—'
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function runLinkParts(runId: string | null): { job: string; attemptId: string } | null {
  if (!runId || !runId.includes(':')) return null
  const [job, attemptId] = runId.split(':', 2)
  if (!job || !attemptId) return null
  return { job, attemptId }
}

/**
 * GCP Logs Explorer–style feed over worker attempt tables + admin_audit_log.
 * Errors and Logs tabs share this panel; Errors locks severity to ERROR.
 */
function OpsLogExplorer({ mode }: { mode: 'errors' | 'logs' }) {
  const [timeWindow, setTimeWindow] = useState<OpsTimeWindow>('1w')
  const [resource, setResource] = useState('')
  const [source, setSource] = useState<'' | 'attempt' | 'audit'>('')
  const [severityFilter, setSeverityFilter] = useState<OpsLogSeverity[]>(
    mode === 'errors' ? ['ERROR'] : ['ERROR', 'WARNING', 'INFO'],
  )
  const [queryDraft, setQueryDraft] = useState('')
  const [query, setQuery] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    setSeverityFilter(mode === 'errors' ? ['ERROR'] : ['ERROR', 'WARNING', 'INFO'])
  }, [mode])

  const allSeveritiesSelected =
    severityFilter.length === LOG_SEVERITY_OPTIONS.length &&
    LOG_SEVERITY_OPTIONS.every((level) => severityFilter.includes(level))

  const logsQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'logs',
      mode,
      timeWindow,
      resource || 'all',
      source || 'all',
      severityFilter.join(','),
      query || '',
    ],
    queryFn: () =>
      listOpsLogs({
        window: timeWindow,
        resource: resource || undefined,
        source: source || undefined,
        severity:
          mode === 'errors'
            ? 'ERROR'
            : allSeveritiesSelected
              ? undefined
              : severityFilter,
        q: query || undefined,
        limit: 100,
      }),
    refetchInterval: 8_000,
    placeholderData: (previous) => previous,
  })

  const entries: OpsLogEntry[] = logsQuery.data ?? []

  function toggleSeverity(level: OpsLogSeverity) {
    if (mode === 'errors') return
    setSeverityFilter((current) => {
      if (current.includes(level)) {
        const next = current.filter((item) => item !== level)
        return next.length > 0 ? next : current
      }
      return [...current, level]
    })
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
            {mode === 'errors' ? 'Errors' : 'Logs'}
          </p>
          <p className="mt-0.5 text-xs text-ink-soft">
            Project-wide feed from worker attempt tables and admin audit — same explorer,
            {mode === 'errors' ? ' filtered to ERROR.' : ' all severities.'}
          </p>
        </div>
        <span className="text-[0.65rem] tabular-nums text-mute">
          {logsQuery.isFetching && !logsQuery.isPending ? 'Refreshing · ' : null}
          {entries.length} entries
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-paper/40 px-2.5 py-2">
        <div className="flex items-center gap-0.5 rounded border border-line p-0.5">
          {LOG_WINDOW_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={cn(
                'rounded px-1.5 py-0.5 text-[0.65rem]',
                timeWindow === option.value
                  ? 'bg-ink text-paper'
                  : 'text-ink-soft hover:bg-paper',
              )}
              onClick={() => setTimeWindow(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        <CompactFilterSelect
          label="Resource"
          value={resource}
          onChange={setResource}
          options={LOG_RESOURCE_OPTIONS}
        />

        <CompactFilterSelect
          label="Source"
          value={source}
          onChange={(value) => setSource(value as '' | 'attempt' | 'audit')}
          options={[
            { value: '', label: 'All sources' },
            { value: 'attempt', label: 'Attempts' },
            { value: 'audit', label: 'Audit' },
          ]}
        />

        <div className="flex items-center gap-1">
          {LOG_SEVERITY_OPTIONS.map((level) => {
            const active = severityFilter.includes(level)
            return (
              <button
                key={level}
                type="button"
                disabled={mode === 'errors'}
                className={cn(
                  'rounded border px-1.5 py-0.5 text-[0.6rem] font-medium uppercase tracking-wide',
                  active ? severityBadgeClass(level) : 'border-line text-mute',
                  mode === 'errors' && 'cursor-default opacity-90',
                )}
                onClick={() => toggleSeverity(level)}
              >
                {level}
              </button>
            )
          })}
        </div>

        <form
          className="ml-auto flex min-w-[12rem] flex-1 items-center gap-1 sm:max-w-xs"
          onSubmit={(event) => {
            event.preventDefault()
            setQuery(queryDraft.trim())
          }}
        >
          <input
            type="search"
            value={queryDraft}
            onChange={(event) => setQueryDraft(event.target.value)}
            placeholder="Filter text…"
            className="h-7 w-full rounded border border-line bg-paper px-2 text-xs text-ink placeholder:text-mute"
            aria-label="Filter log messages"
          />
          <Button type="submit" size="sm" variant="outline" className="h-7 px-2 text-[0.65rem]">
            Apply
          </Button>
        </form>
      </div>

      <div className="overflow-hidden rounded-md border border-line">
        {logsQuery.isError ? (
          <p className="px-3 py-3 text-xs text-red-700">
            Could not load ops logs from admin-api.
          </p>
        ) : logsQuery.isPending && !logsQuery.data ? (
          <div className="p-3">
            <SkeletonLines lines={5} />
          </div>
        ) : entries.length === 0 ? (
          <p className="px-3 py-3 text-xs text-ink-soft">
            {mode === 'errors'
              ? 'No errors in the selected window.'
              : 'No log entries in the selected window.'}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="taste-table">
              <thead>
                <tr>
                  <th className="w-[9.5rem]">Time</th>
                  <th className="w-[5.5rem]">Severity</th>
                  <th className="w-[8rem]">Resource</th>
                  <th>Message</th>
                  <th className="w-[5rem]">Source</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => {
                  const open = expandedId === entry.id
                  const link = runLinkParts(entry.run_id)
                  return (
                    <Fragment key={entry.id}>
                      <tr
                        className={cn(
                          'cursor-pointer',
                          entry.severity === 'ERROR' && 'bg-red-50/30',
                        )}
                        onClick={() => setExpandedId(open ? null : entry.id)}
                      >
                        <td className="whitespace-nowrap tabular-nums text-[0.65rem] text-ink-soft">
                          {formatLogTimestamp(entry.timestamp)}
                        </td>
                        <td>
                          <span
                            className={cn(
                              'inline-block rounded border px-1 py-px text-[0.55rem] font-semibold uppercase tracking-wide',
                              severityBadgeClass(entry.severity),
                            )}
                          >
                            {entry.severity}
                          </span>
                        </td>
                        <td className="font-mono text-[0.65rem]">{entry.resource}</td>
                        <td className="max-w-[28rem] truncate text-xs" title={entry.message}>
                          {entry.message}
                        </td>
                        <td className="text-[0.65rem] text-mute">{entry.source}</td>
                      </tr>
                      {open ? (
                        <tr className="bg-paper/60">
                          <td colSpan={5} className="px-3 py-2.5">
                            <dl className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
                              <div>
                                <dt className="text-[0.6rem] uppercase tracking-wide text-mute">
                                  Id
                                </dt>
                                <dd className="font-mono text-[0.65rem]">{entry.id}</dd>
                              </div>
                              {entry.step ? (
                                <div>
                                  <dt className="text-[0.6rem] uppercase tracking-wide text-mute">
                                    Step
                                  </dt>
                                  <dd className="font-mono text-[0.65rem]">{entry.step}</dd>
                                </div>
                              ) : null}
                              {entry.status ? (
                                <div>
                                  <dt className="text-[0.6rem] uppercase tracking-wide text-mute">
                                    {entry.source === 'audit' ? 'Command' : 'Status'}
                                  </dt>
                                  <dd className="font-mono text-[0.65rem]">{entry.status}</dd>
                                </div>
                              ) : null}
                              {entry.error_code ? (
                                <div>
                                  <dt className="text-[0.6rem] uppercase tracking-wide text-mute">
                                    Error code
                                  </dt>
                                  <dd className="font-mono text-[0.65rem]">{entry.error_code}</dd>
                                </div>
                              ) : null}
                              {entry.actor ? (
                                <div>
                                  <dt className="text-[0.6rem] uppercase tracking-wide text-mute">
                                    Actor
                                  </dt>
                                  <dd className="font-mono text-[0.65rem]">{entry.actor}</dd>
                                </div>
                              ) : null}
                              {entry.result_status != null ? (
                                <div>
                                  <dt className="text-[0.6rem] uppercase tracking-wide text-mute">
                                    HTTP
                                  </dt>
                                  <dd className="tabular-nums text-[0.65rem]">
                                    {entry.result_status}
                                  </dd>
                                </div>
                              ) : null}
                              {entry.request_id ? (
                                <div>
                                  <dt className="text-[0.6rem] uppercase tracking-wide text-mute">
                                    Request
                                  </dt>
                                  <dd>
                                    <Link
                                      to="/requests/$requestId"
                                      params={{ requestId: entry.request_id }}
                                      className="font-mono text-[0.65rem] text-habeas-mid underline decoration-habeas-mid/30 underline-offset-2"
                                      onClick={(event) => event.stopPropagation()}
                                    >
                                      {entry.request_id}
                                    </Link>
                                  </dd>
                                </div>
                              ) : null}
                              {link ? (
                                <div>
                                  <dt className="text-[0.6rem] uppercase tracking-wide text-mute">
                                    Run
                                  </dt>
                                  <dd>
                                    <Link
                                      to="/ops/runs/$job/$attemptId"
                                      params={{
                                        job: link.job,
                                        attemptId: link.attemptId,
                                      }}
                                      className="font-mono text-[0.65rem] text-habeas-mid underline decoration-habeas-mid/30 underline-offset-2"
                                      onClick={(event) => event.stopPropagation()}
                                    >
                                      {entry.run_id}
                                    </Link>
                                  </dd>
                                </div>
                              ) : null}
                            </dl>
                            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded border border-line bg-paper px-2 py-1.5 font-mono text-[0.65rem] text-ink-soft">
                              {entry.message}
                            </pre>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

/** Only feature a bulk process as "current" when recent + not finished. */
const ACTIVE_BULK_MAX_AGE_MS = 48 * 60 * 60 * 1000

function isActiveBulkDetail(detail: BulkProcessDetail | undefined): boolean {
  if (!detail?.process_at) return false
  const status = detail.overall.status
  if (status !== 'in_progress' && status !== 'needs_attention') return false
  const ageMs = Date.now() - new Date(detail.process_at).getTime()
  return ageMs >= 0 && ageMs <= ACTIVE_BULK_MAX_AGE_MS
}

async function loadBatchRequestRuns(params: {
  days: number
  intake: string
  downloadStatus: string
  overallStatus: string
}): Promise<BulkProcessesPayload> {
  return listDropBulkProcesses({
    days: params.days,
    intake_source: params.intake || undefined,
    download_status: params.downloadStatus || undefined,
    overall_status: params.overallStatus || undefined,
    include_summary: true,
    limit: 50,
  })
}

function isActiveBulkSummary(row: BulkProcessSummary): boolean {
  if (!row.process_at) return false
  const status = row.overall?.status
  if (status !== 'in_progress' && status !== 'needs_attention') return false
  const ageMs = Date.now() - new Date(row.process_at).getTime()
  return ageMs >= 0 && ageMs <= ACTIVE_BULK_MAX_AGE_MS
}

function formatDurationMs(ms: number | null | undefined): string | null {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return null
  const minutes = Math.floor(ms / 60_000)
  if (minutes < 60) return `${Math.max(minutes, 0)}m`
  const hours = Math.floor(minutes / 60)
  const rem = minutes % 60
  if (hours < 48) return rem > 0 ? `${hours}h ${rem}m` : `${hours}h`
  const days = Math.floor(hours / 24)
  const dayRem = hours % 24
  return dayRem > 0 ? `${days}d ${dayRem}h` : `${days}d`
}

function durationMsBetween(
  startAt: string | null | undefined,
  endAt?: string | null,
): number | null {
  if (!startAt) return null
  const start = new Date(startAt).getTime()
  if (Number.isNaN(start)) return null
  const end = endAt ? new Date(endAt).getTime() : Date.now()
  if (Number.isNaN(end) || end < start) return null
  return end - start
}

/** Wall-clock span for a process stage group. Open runs end at now unless requireComplete. */
function stageDurationMsFromGroup(
  group: BulkProcessRunGroup | undefined,
  opts?: { requireComplete?: boolean },
): number | null {
  if (!group?.runs.length) return null
  let earliest: number | null = null
  let latest: number | null = null
  let anyOpen = false
  for (const run of group.runs) {
    if (!run.started_at) continue
    const start = new Date(run.started_at).getTime()
    if (Number.isNaN(start)) continue
    if (earliest == null || start < earliest) earliest = start
    if (run.completed_at) {
      const end = new Date(run.completed_at).getTime()
      if (!Number.isNaN(end) && (latest == null || end > latest)) latest = end
    } else {
      anyOpen = true
    }
  }
  if (earliest == null) return null
  if (opts?.requireComplete) {
    if (anyOpen || latest == null) return null
    return latest - earliest
  }
  const end = anyOpen || latest == null ? Date.now() : latest
  if (end < earliest) return null
  return end - earliest
}

/** Mean completed bulk duration in the peer window (same intake when set). */
function averageBulkDurationMs(
  peers: BulkProcessSummary[],
  opts: { intakeSource?: string | null; excludeProcessId: number },
): number | null {
  const samples: number[] = []
  for (const peer of peers) {
    if (peer.process_id === opts.excludeProcessId) continue
    if (opts.intakeSource && peer.intake_source !== opts.intakeSource) continue
    if (!peer.process_at || !peer.completed_at) continue
    const ms = durationMsBetween(peer.process_at, peer.completed_at)
    if (ms != null && ms > 0) samples.push(ms)
  }
  if (samples.length === 0) return null
  return samples.reduce((sum, value) => sum + value, 0) / samples.length
}

/** Mean completed stage wall-clock across peer process groups. */
function averageStageDurationMs(
  groups: BulkProcessRunGroup[] | undefined,
  opts: { intakeSource?: string | null; excludeProcessId: number },
): number | null {
  if (!groups?.length) return null
  const samples: number[] = []
  for (const group of groups) {
    if (group.process_id === opts.excludeProcessId) continue
    if (opts.intakeSource && group.intake_source !== opts.intakeSource) continue
    const ms = stageDurationMsFromGroup(group, { requireComplete: true })
    if (ms != null && ms > 0) samples.push(ms)
  }
  if (samples.length === 0) return null
  return samples.reduce((sum, value) => sum + value, 0) / samples.length
}

function durationVsAvgHint(
  currentMs: number | null,
  avgMs: number | null,
): { avgLabel: string; deltaLabel: string | null; ofAvgPercent: number | null } | null {
  const avgLabel = formatDurationMs(avgMs)
  if (avgMs == null || avgLabel == null) return null
  if (currentMs == null || avgMs <= 0) {
    return { avgLabel, deltaLabel: null, ofAvgPercent: null }
  }
  const deltaMs = currentMs - avgMs
  const absLabel = formatDurationMs(Math.abs(deltaMs))
  const deltaLabel =
    absLabel == null
      ? null
      : deltaMs === 0
        ? 'at avg'
        : deltaMs < 0
          ? `−${absLabel} vs avg`
          : `+${absLabel} vs avg`
  return {
    avgLabel,
    deltaLabel,
    ofAvgPercent: Math.round((currentMs / avgMs) * 100),
  }
}

/** Human title for bulk cards from process_at (e.g. Jul 22, 2026, 2:00 PM). */
function formatBulkProcessName(processAt: string | null | undefined): string {
  if (!processAt) return '—'
  const start = new Date(processAt)
  if (Number.isNaN(start.getTime())) return '—'
  return start.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function stageRunIndicators(counts: BulkProcessStageCounts | undefined): {
  finished: number
  queued: number
  inFlight: number
  failed: number
  abandoned: number
  percent: number
} {
  if (!counts || counts.total <= 0) {
    return {
      finished: 0,
      queued: 0,
      inFlight: 0,
      failed: 0,
      abandoned: 0,
      percent: 0,
    }
  }
  const byStatus = new Map<string, number>()
  for (const row of counts.by_list_type ?? []) {
    const key = row.status.toLowerCase()
    byStatus.set(key, (byStatus.get(key) ?? 0) + row.count)
  }
  const abandoned =
    byStatus.get('abandoned') ??
    (counts.by_list_type?.length ? 0 : (counts.other ?? 0))
  const failed = Math.max(0, counts.failed - abandoned)
  const hasStatusBreakdown = (counts.by_list_type?.length ?? 0) > 0
  const queued = hasStatusBreakdown
    ? byStatus.get('pending') ?? 0
    : counts.open
  const inFlight = hasStatusBreakdown
    ? (byStatus.get('claimed') ?? 0) +
      (byStatus.get('in_flight') ?? 0) +
      (byStatus.get('leased') ?? 0)
    : 0
  return {
    finished: counts.success,
    queued,
    inFlight,
    failed,
    abandoned,
    percent: Math.round((counts.success / counts.total) * 100),
  }
}

function bulkDerivedStats(detail: BulkProcessDetail | undefined): {
  open: number
  failed: number
  reviewOpen: number
  matchOpen: number
  fulfillOpen: number
  listTypes: string | null
} {
  if (!detail) {
    return {
      open: 0,
      failed: 0,
      reviewOpen: 0,
      matchOpen: 0,
      fulfillOpen: 0,
      listTypes: null,
    }
  }
  const stageKeys = Object.keys(detail.stages) as (keyof BulkProcessDetail['stages'])[]
  let open = 0
  let failed = 0
  for (const key of stageKeys) {
    const stage = detail.stages[key]
    open += stage.open
    failed += stage.failed
  }
  const listTypes =
    detail.stages.land.by_list_type
      ?.filter((row) => row.list_type)
      .reduce<string[]>((acc, row) => {
        const label = String(row.list_type)
        if (!acc.includes(label)) acc.push(label)
        return acc
      }, [])
      .slice(0, 3)
      .join(', ') ?? null
  return {
    open,
    failed,
    reviewOpen: detail.stages.review.open,
    matchOpen: detail.stages.matching.open,
    fulfillOpen: detail.stages.fulfillment.open,
    listTypes: listTypes || null,
  }
}

function StatusLight({
  tone = 'mute',
  pulse = false,
  title,
}: {
  tone?: 'emerald' | 'sky' | 'amber' | 'red' | 'mute' | 'navy'
  pulse?: boolean
  title?: string
}) {
  const fill =
    tone === 'emerald'
      ? 'bg-emerald-500'
      : tone === 'sky'
        ? 'bg-sky-500'
        : tone === 'amber'
          ? 'bg-amber-500'
          : tone === 'red'
            ? 'bg-red-500'
            : tone === 'navy'
              ? 'bg-habeas-navy'
              : 'bg-mute/70'
  return (
    <span
      className="relative inline-flex h-1.5 w-1.5 shrink-0"
      title={title}
      aria-hidden={title ? undefined : true}
    >
      {pulse ? (
        <span
          className={`absolute inline-flex h-full w-full animate-ping rounded-full ${fill} opacity-60`}
        />
      ) : null}
      <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${fill}`} />
    </span>
  )
}

function NeedsReviewChip({ count }: { count?: number | null }) {
  const label =
    count != null && count > 0
      ? `${count} need${count === 1 ? 's' : ''} review`
      : 'Needs review'
  return (
    <span className="inline-flex items-center gap-1 rounded border border-amber-300/80 bg-amber-50 px-1.5 py-0.5 text-[0.6rem] font-medium uppercase tracking-wide text-amber-950">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden="true" />
      {label}
    </span>
  )
}

function isPendingBulkSummary(row: BulkProcessSummary): boolean {
  const download = row.download_status
  if (download === 'pending' || download === 'in_flight') return true
  return row.overall?.status === 'in_progress' && (row.overall.percent ?? 0) < 5
}

function MiniRing({
  percent,
  tone = 'navy',
}: {
  percent: number
  tone?: 'navy' | 'emerald' | 'red' | 'amber'
}) {
  const clamped = Math.max(0, Math.min(100, percent))
  const color =
    tone === 'emerald'
      ? 'stroke-emerald-600'
      : tone === 'red'
        ? 'stroke-red-600'
        : tone === 'amber'
          ? 'stroke-amber-600'
          : 'stroke-habeas-navy'
  const r = 14
  const c = 2 * Math.PI * r
  const offset = c - (clamped / 100) * c
  return (
    <svg viewBox="0 0 36 36" className="h-9 w-9 shrink-0" aria-hidden="true">
      <circle
        cx="18"
        cy="18"
        r={r}
        fill="none"
        className="stroke-line"
        strokeWidth="3"
      />
      <circle
        cx="18"
        cy="18"
        r={r}
        fill="none"
        className={color}
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={offset}
        transform="rotate(-90 18 18)"
      />
    </svg>
  )
}

function BulkStageStrip({
  detail,
  loading,
  duration,
  running,
  activeTab,
  onSelectTab,
  expanded,
}: {
  detail: BulkProcessDetail | undefined
  loading?: boolean
  duration?: string | null
  running?: boolean
  activeTab: PipelineStageTab
  onSelectTab: (tab: PipelineStageTab) => void
  expanded: boolean
}) {
  return (
    <div
      className="flex min-w-0 items-stretch gap-1 overflow-x-auto"
      role="tablist"
      aria-label="Bulk process stages"
    >
      {BULK_CARD_STAGE_TABS.map((tab) => {
        if (loading || !detail) {
          return (
            <div
              key={tab.key}
              className={
                expanded
                  ? 'min-w-[4.5rem] flex-1 rounded px-1.5 py-1'
                  : 'min-w-[3.25rem] shrink-0 rounded px-1 py-0.5'
              }
            >
              <Skeleton className={expanded ? 'h-5 w-full' : 'h-3 w-full'} />
            </div>
          )
        }
        const counts = countsForStageTab(detail, tab)
        const isCurrent = isStageTabCurrent(detail, tab)
        const selected = activeTab === tab.key
        const emphasize = expanded && selected
        const visual = stageVisualState(counts, isCurrent)
        const indicators = stageRunIndicators(counts)
        const tone = stageStripTone(visual)
        const currentRunning =
          isCurrent && Boolean(running) && visual !== 'complete'
        const currentCompact = expanded && isCurrent && !selected

        if (!emphasize) {
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={(event) => {
                event.stopPropagation()
                onSelectTab(tab.key)
              }}
              className={cn(
                'flex shrink-0 items-center gap-1 rounded text-left transition-colors hover:bg-panel/50',
                expanded ? 'px-1.5 py-1' : 'px-1 py-0.5',
                tone.wash,
                currentCompact && 'border-l-2 border-l-emerald-500',
              )}
              title={
                counts
                  ? `${tab.label}: ${stageCountsBlurb(counts)}${
                      isCurrent ? ' · current' : ''
                    }`
                  : tab.label
              }
            >
              <StatusLight
                tone={
                  visual === 'complete'
                    ? 'emerald'
                    : visual === 'failed'
                      ? 'red'
                      : currentRunning || currentCompact
                        ? 'emerald'
                        : tone.light
                }
                pulse={currentRunning || currentCompact}
                title={
                  visual === 'complete'
                    ? 'Done'
                    : currentRunning || currentCompact
                      ? 'Running'
                      : visual === 'failed'
                        ? 'Failed'
                        : undefined
                }
              />
              <span
                className={cn(
                  'truncate text-[0.55rem] font-medium leading-none tracking-wide',
                  visual === 'complete' ||
                    currentRunning ||
                    currentCompact ||
                    visual === 'failed'
                    ? tone.text
                    : 'text-mute',
                )}
              >
                {tab.label}
              </span>
            </button>
          )
        }

        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={(event) => {
              event.stopPropagation()
              onSelectTab(tab.key)
            }}
            className={cn(
              'flex min-h-[3.25rem] min-w-[10rem] flex-1 flex-col justify-center rounded-md px-2.5 py-2.5 text-left transition-colors',
              tone.wash,
              'bg-habeas-navy/8 ring-1 ring-inset ring-habeas-navy/25',
            )}
            title={
              counts
                ? `${tab.label}: ${stageCountsBlurb(counts)}${
                    duration ? ` · ${duration}` : ''
                  }`
                : tab.label
            }
          >
            <div className="flex min-w-0 items-center gap-1.5">
              <StatusLight
                tone={
                  visual === 'complete'
                    ? 'emerald'
                    : visual === 'failed'
                      ? 'red'
                      : currentRunning
                        ? 'emerald'
                        : tone.light
                }
                pulse={currentRunning}
                title={
                  visual === 'complete'
                    ? 'Done'
                    : currentRunning
                      ? 'Running'
                      : visual === 'failed'
                        ? 'Failed'
                        : undefined
                }
              />
              <span
                className={cn(
                  'truncate text-[0.65rem] font-semibold leading-none tracking-wide',
                  tone.text,
                )}
              >
                {tab.label}
                {isCurrent ? (
                  <span className="ml-1 font-normal text-mute">· current</span>
                ) : null}
              </span>
              <span className="ml-auto shrink-0 text-sm font-medium tabular-nums leading-none text-ink">
                {counts && counts.total > 0 ? `${indicators.percent}%` : '—'}
              </span>
            </div>
            <div className="relative mt-1.5 h-1.5 overflow-hidden rounded-full bg-line/60">
              <div
                className={cn(
                  'h-full rounded-full transition-[width]',
                  visual === 'failed' ? 'bg-red-600' : tone.bar,
                )}
                style={{ width: `${indicators.percent}%` }}
              />
              {currentRunning ? (
                <div className="pointer-events-none absolute inset-0 animate-pulse bg-gradient-to-r from-transparent via-white/50 to-transparent" />
              ) : null}
            </div>
          </button>
        )
      })}
    </div>
  )
}

const STAGE_STATE_CARDS: {
  key: BulkStageRunState
  label: string
  tone: string
}[] = [
  { key: 'queued', label: 'Queued', tone: 'text-sky-950' },
  { key: 'in_flight', label: 'In flight', tone: 'text-habeas-navy' },
  { key: 'failed', label: 'Failed', tone: 'text-red-800' },
  { key: 'abandoned', label: 'Abandoned', tone: 'text-amber-950' },
  { key: 'finished', label: 'Finished', tone: 'text-emerald-900' },
]

function DurationMetricChip({
  label,
  value,
  running,
  avgHint,
  avgTitle,
  ofAvgPercent,
}: {
  label: string
  value: string | null | undefined
  running?: boolean
  /** Compact historical average, e.g. "avg 18m". */
  avgHint?: string | null
  /** Richer tooltip (avg + delta). */
  avgTitle?: string | null
  /** Current duration as % of average — drives the ring when known. */
  ofAvgPercent?: number | null
}) {
  const display = value && value.length > 0 ? value : '—'
  const known = display !== '—'
  const ringPercent =
    ofAvgPercent != null && Number.isFinite(ofAvgPercent)
      ? Math.max(4, Math.min(100, ofAvgPercent))
      : running
        ? 55
        : known
          ? 100
          : 0
  const compare = avgTitle ?? avgHint
  const title =
    compare && known
      ? `${label}: ${display}${running ? '…' : ''} (${compare})`
      : compare
        ? `${label}: ${compare}`
        : undefined
  return (
    <div
      className="flex min-w-[8.5rem] flex-1 basis-[8.5rem] items-center gap-2 rounded-md border border-line bg-paper px-2.5 py-1.5"
      title={title}
    >
      {known || avgHint ? (
        <MiniRing
          percent={known ? ringPercent : 0}
          tone={running ? 'emerald' : 'navy'}
        />
      ) : (
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-dashed border-line text-[0.55rem] text-mute"
          aria-hidden="true"
        >
          —
        </div>
      )}
      <div className="min-w-0">
        <p className="text-[0.5rem] font-medium uppercase tracking-wide text-mute">
          {label}
        </p>
        <p className="text-xs font-semibold tabular-nums leading-tight text-ink">
          {display}
          {known && running ? '…' : ''}
        </p>
        {avgHint ? (
          <p className="mt-0.5 text-[0.55rem] tabular-nums leading-none text-mute">
            {avgHint}
          </p>
        ) : null}
      </div>
    </div>
  )
}

function BulkStageStateCards({
  stageTab,
  processId,
  indicators,
  loading,
  stageDuration,
  bulkDuration,
  stageAvgHint,
  bulkAvgHint,
  stageAvgTitle,
  bulkAvgTitle,
  stageOfAvgPercent,
  bulkOfAvgPercent,
  running,
}: {
  stageTab: PipelineStageTab
  processId: number
  indicators: ReturnType<typeof stageRunIndicators>
  loading?: boolean
  stageDuration?: string | null
  bulkDuration?: string | null
  stageAvgHint?: string | null
  bulkAvgHint?: string | null
  stageAvgTitle?: string | null
  bulkAvgTitle?: string | null
  stageOfAvgPercent?: number | null
  bulkOfAvgPercent?: number | null
  running?: boolean
}) {
  const counts: Record<BulkStageRunState, number> = {
    queued: indicators.queued,
    in_flight: indicators.inFlight,
    failed: indicators.failed,
    abandoned: indicators.abandoned,
    finished: indicators.finished,
  }
  // Fulfillment cards stay compact — duration chips share the row.
  const compact = stageTab === 'fulfillment' || stageTab === 'review'

  if (loading) {
    return (
      <div className="flex flex-wrap items-stretch gap-1.5">
        {STAGE_STATE_CARDS.map((card) => (
          <div
            key={card.key}
            className={cn(
              'min-h-[3rem] rounded-md border border-line/70 bg-paper px-2 py-1.5',
              compact ? 'w-[4.5rem]' : 'min-w-[5.5rem] flex-1',
            )}
          >
            <Skeleton className="h-8 w-full" />
          </div>
        ))}
        <Skeleton className="h-[3.25rem] min-w-[8.5rem] flex-1 basis-[8.5rem]" />
        <Skeleton className="h-[3.25rem] min-w-[8.5rem] flex-1 basis-[8.5rem]" />
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-stretch gap-1.5">
      {STAGE_STATE_CARDS.map((card) => (
        <Link
          key={card.key}
          to="/ops/runs"
          search={runsSearchForBulkStage(stageTab, card.key, {
            process: processId,
          })}
          className={cn(
            'min-h-[3rem] rounded-md border border-line bg-paper px-2 py-1.5 text-left transition-colors hover:border-habeas-navy/35 hover:bg-panel/40',
            compact ? 'w-[4.5rem] shrink-0' : 'min-w-[5.5rem] flex-1',
          )}
        >
          <p className="text-[0.5rem] font-medium uppercase tracking-wide text-mute">
            {card.label}
          </p>
          <p
            className={cn(
              'mt-0.5 text-sm font-semibold tabular-nums',
              card.tone,
            )}
          >
            {counts[card.key]}
          </p>
        </Link>
      ))}
      <DurationMetricChip
        label="Stage dur"
        value={stageDuration}
        running={running && indicators.percent < 100}
        avgHint={stageAvgHint}
        avgTitle={stageAvgTitle}
        ofAvgPercent={stageOfAvgPercent}
      />
      <DurationMetricChip
        label="Bulk dur"
        value={bulkDuration}
        running={running}
        avgHint={bulkAvgHint}
        avgTitle={bulkAvgTitle}
        ofAvgPercent={bulkOfAvgPercent}
      />
    </div>
  )
}

function stageTabFromOverall(
  current: string | undefined | null,
): PipelineStageTab {
  const stage = (current ?? '').toLowerCase()
  if (stage === 'download') return 'download'
  if (stage === 'land' || stage === 'promote') return 'ingest'
  if (stage === 'matching') return 'matching'
  if (stage === 'review') return 'review'
  if (stage === 'fulfillment' || stage === 'fulfill') return 'fulfillment'
  return 'download'
}

function BatchProcessExpandRow({
  row,
  expanded,
  onToggle,
  focusedStage,
  peerProcesses,
  historyDays,
}: {
  row: BulkProcessSummary
  expanded: boolean
  onToggle: () => void
  focusedStage?: PipelineStageTab
  /** Kept for callers; stage tabs stay local — do not write URL on every click. */
  onStageChange?: (stage: PipelineStageTab) => void
  /** Sibling bulks in the list window — used for bulk-duration average. */
  peerProcesses: BulkProcessSummary[]
  /** Window (days) for stage-run history averages. */
  historyDays: number
}) {
  const statusKey = row.overall?.status ?? row.download_status
  const likelyNeedsReview = statusKey === 'needs_attention'
  const detailQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-processes', 'detail', row.process_id],
    queryFn: () => getDropBulkProcess(row.process_id),
    enabled: true,
    refetchInterval:
      expanded || likelyNeedsReview || isActiveBulkSummary(row) ? 5_000 : 30_000,
    placeholderData: (previous) => previous,
  })
  const appliedFocusedOnExpand = useRef(false)
  const [stageTab, setStageTab] = useState<PipelineStageTab>(
    focusedStage ?? stageTabFromOverall(row.overall?.current_stage) ?? 'download',
  )
  const activeStage =
    BULK_CARD_STAGE_TABS.find((tab) => tab.key === stageTab) ?? BULK_CARD_STAGE_TABS[0]

  const detail = detailQuery.data
  const running = isActiveBulkSummary(row) || isActiveBulkDetail(detail)
  const pending = !running && isPendingBulkSummary(row)
  const percent = detail?.overall.percent ?? row.overall?.percent
  const resolvedStatusKey =
    detail?.overall.status ?? row.overall?.status ?? row.download_status
  const status = resolvedStatusKey.replaceAll('_', ' ')
  const requestRows = detail?.request_rows ?? row.request_rows
  const completedAt = detail?.completed_at ?? row.completed_at
  const bulkDurationMs = durationMsBetween(
    row.process_at,
    running ? null : completedAt,
  )
  const duration = formatDurationMs(bulkDurationMs)
  // Shared across expanded cards (no process_id) so stage averages reuse one cache entry.
  const stageRunsQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'drop-process-runs',
      'stage-duration-history',
      historyDays,
      activeStage.runStage,
    ],
    queryFn: () =>
      listDropBulkProcessRuns({
        stage: activeStage.runStage,
        days: historyDays,
      }),
    enabled: expanded,
    staleTime: 15_000,
    placeholderData: (previous) => previous,
  })
  const stageGroups = stageRunsQuery.data?.groups
  const stageDurationMs = stageDurationMsFromGroup(
    stageGroups?.find((group) => group.process_id === row.process_id),
  )
  const stageDuration = formatDurationMs(stageDurationMs)
  const bulkAvgMs = averageBulkDurationMs(peerProcesses, {
    intakeSource: row.intake_source,
    excludeProcessId: row.process_id,
  })
  const stageAvgMs = averageStageDurationMs(stageGroups, {
    intakeSource: row.intake_source,
    excludeProcessId: row.process_id,
  })
  const bulkVsAvg = durationVsAvgHint(bulkDurationMs, bulkAvgMs)
  const stageVsAvg = durationVsAvgHint(stageDurationMs, stageAvgMs)
  const bulkAvgHint = bulkVsAvg ? `avg ${bulkVsAvg.avgLabel}` : null
  const stageAvgHint = stageVsAvg ? `avg ${stageVsAvg.avgLabel}` : null
  const bulkAvgTitle = bulkVsAvg?.deltaLabel
    ? `${bulkAvgHint} · ${bulkVsAvg.deltaLabel}`
    : bulkAvgHint
  const stageAvgTitle = stageVsAvg?.deltaLabel
    ? `${stageAvgHint} · ${stageVsAvg.deltaLabel}`
    : stageAvgHint
  const derived = bulkDerivedStats(detail)
  const needsReview =
    resolvedStatusKey === 'needs_attention' || derived.reviewOpen > 0
  const reviewCount = derived.reviewOpen > 0 ? derived.reviewOpen : null
  const activeTabCounts = countsForStageTab(detail, activeStage)
  const activeIndicators = stageRunIndicators(activeTabCounts)
  const estCompletion = activeIndicators.percent
  const errorRate =
    activeTabCounts && activeTabCounts.total > 0
      ? Math.round(
          ((activeIndicators.failed + activeIndicators.abandoned) /
            activeTabCounts.total) *
            100,
        )
      : 0

  useEffect(() => {
    if (!expanded) {
      appliedFocusedOnExpand.current = false
      return
    }
    if (appliedFocusedOnExpand.current) return
    appliedFocusedOnExpand.current = true
    if (focusedStage) {
      setStageTab(focusedStage)
      return
    }
    setStageTab(
      stageTabFromOverall(
        detail?.overall.current_stage ?? row.overall?.current_stage,
      ),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded, focusedStage])

  function selectStage(next: PipelineStageTab) {
    setStageTab(next)
  }

  const processName = formatBulkProcessName(row.process_at)
  const rowTone = running
    ? 'border-b border-emerald-200/70 bg-emerald-50/30 last:border-b-0'
    : pending
      ? 'border-b border-sky-200/70 bg-sky-50/25 last:border-b-0'
      : needsReview
        ? 'border-b border-amber-200/70 bg-amber-50/25 last:border-b-0'
        : 'border-b border-line bg-paper last:border-b-0'

  return (
    <div className={rowTone}>
      <div className="flex flex-col gap-0.5 px-3 py-1">
        <div className="flex w-full items-center gap-2">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            className={
              running
                ? 'flex min-w-0 flex-1 items-center gap-2 border-l-2 border-l-emerald-500 pl-2 text-left'
                : pending
                  ? 'flex min-w-0 flex-1 items-center gap-2 border-l-2 border-l-sky-400 pl-2 text-left'
                  : needsReview
                    ? 'flex min-w-0 flex-1 items-center gap-2 border-l-2 border-l-amber-400 pl-2 text-left'
                    : 'flex min-w-0 flex-1 items-center gap-2 border-l-2 border-l-transparent pl-2 text-left'
            }
          >
            <span
              className="inline-flex h-5 w-5 shrink-0 items-center justify-center text-[0.65rem] text-mute"
              aria-hidden="true"
            >
              {expanded ? '▼' : '▶'}
            </span>
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
              <p className="truncate text-xs font-medium text-ink">{processName}</p>
              {running ? (
                <StatusLight tone="emerald" pulse title="Running" />
              ) : null}
              {pending ? (
                <StatusLight tone="sky" pulse title="Pending" />
              ) : null}
              {needsReview ? <NeedsReviewChip count={reviewCount} /> : null}
              {derived.failed > 0 ? (
                <span className="text-[0.6rem] text-red-700">
                  {derived.failed} failed
                </span>
              ) : null}
              {!running && !pending && !needsReview ? (
                <span className="text-[0.6rem] capitalize text-mute">{status}</span>
              ) : null}
              <span className="ml-auto flex shrink-0 items-center gap-2 text-[0.6rem] tabular-nums text-mute">
                <span>
                  Dur {duration ?? '—'}
                  {duration && running ? '…' : ''}
                </span>
                {expanded ? (
                  <span>
                    Est {estCompletion}% · err {errorRate}%
                  </span>
                ) : (
                  <span>
                    Prog {percent != null ? `${percent}%` : '—'}
                    {requestRows != null ? ` · ${requestRows} req` : ''}
                  </span>
                )}
              </span>
            </div>
          </button>
        </div>

        <div className="w-full pl-7">
          <BulkStageStrip
            detail={detail}
            loading={detailQuery.isPending && !detail}
            duration={duration}
            running={running || pending}
            activeTab={stageTab}
            onSelectTab={selectStage}
            expanded={expanded}
          />
        </div>
      </div>

      {expanded ? (
        <div
          className={
            running
              ? 'space-y-1.5 border-t border-emerald-100/80 bg-emerald-50/15 px-3 py-1.5 pl-10'
              : pending
                ? 'space-y-1.5 border-t border-sky-100/80 bg-sky-50/15 px-3 py-1.5 pl-10'
                : needsReview
                  ? 'space-y-1.5 border-t border-amber-100/80 bg-amber-50/15 px-3 py-1.5 pl-10'
                  : 'space-y-1.5 border-t border-line/60 px-3 py-1.5 pl-10'
          }
        >
          {detailQuery.isError ? (
            <p className="text-[0.65rem] text-red-700">Could not load stage detail</p>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[0.6rem] font-medium uppercase tracking-wide text-mute">
              {activeStage.label} run states
            </p>
            {stageTab === 'review' ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Link
                    to="/requests/needs-attention"
                    search={{ bulk: row.process_id }}
                    className="taste-btn inline-flex px-2 py-0.5 text-[0.6rem]"
                  >
                    Matching results
                    {derived.reviewOpen > 0 ? ` · ${derived.reviewOpen}` : ''}
                  </Link>
                </TooltipTrigger>
                <TooltipContent>
                  Review fulfill / decline for this bulk in Inbox
                </TooltipContent>
              </Tooltip>
            ) : null}
          </div>

          <BulkStageStateCards
            stageTab={stageTab}
            processId={row.process_id}
            indicators={activeIndicators}
            loading={detailQuery.isPending && !detail}
            stageDuration={stageDuration}
            bulkDuration={duration}
            stageAvgHint={stageAvgHint}
            bulkAvgHint={bulkAvgHint}
            stageAvgTitle={stageAvgTitle}
            bulkAvgTitle={bulkAvgTitle}
            stageOfAvgPercent={stageVsAvg?.ofAvgPercent}
            bulkOfAvgPercent={bulkVsAvg?.ofAvgPercent}
            running={running || pending}
          />
          {stageTab === 'fulfillment' ? (
            <p className="text-[0.6rem] text-mute">
              Fulfillment is tracked per request response status; cards link to
              matching-job runs as the closest Runs filter.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}


function BatchRequestRunsList({
  onSelectProcess,
  selectedProcessId,
  focusedStage,
  onStageChange,
}: {
  onSelectProcess: (id: number) => void
  selectedProcessId?: number
  focusedStage?: PipelineStageTab
  onStageChange?: (stage: PipelineStageTab) => void
}) {
  const [viewMode, setViewMode] = useState<'bulk' | 'individual'>('bulk')
  const [days, setDays] = useState(7)
  const [intake, setIntake] = useState('drop')
  const [downloadStatus, setDownloadStatus] = useState('')
  const [overallStatus, setOverallStatus] = useState('')
  const [runStatusFilter, setRunStatusFilter] = useState('attention')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const didAutoExpand = useRef(false)

  const listQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'drop-processes',
      'pipeline-list',
      days,
      intake,
      downloadStatus,
      overallStatus,
    ],
    queryFn: () =>
      loadBatchRequestRuns({
        days,
        intake,
        downloadStatus,
        overallStatus,
      }),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const rows = listQuery.data?.processes ?? []
  const activeCount = rows.filter((row) => isActiveBulkSummary(row)).length
  const pendingCount = rows.filter(
    (row) => !isActiveBulkSummary(row) && isPendingBulkSummary(row),
  ).length
  const errorMessage =
    listQuery.error instanceof Error ? listQuery.error.message : 'Could not load batch runs.'

  useEffect(() => {
    if (didAutoExpand.current || rows.length === 0 || viewMode !== 'bulk') return
    const active = rows.find((row) => isActiveBulkSummary(row))
    if (active) {
      didAutoExpand.current = true
      setExpandedId(active.process_id)
      onSelectProcess(active.process_id)
      return
    }
    if (selectedProcessId != null && rows.some((row) => row.process_id === selectedProcessId)) {
      didAutoExpand.current = true
      setExpandedId(selectedProcessId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- auto-expand once when list arrives
  }, [rows, viewMode])

  function toggle(processId: number) {
    setExpandedId((current) => {
      const next = current === processId ? null : processId
      if (next != null) onSelectProcess(next)
      return next
    })
  }

  return (
    <div className="rounded-md border border-line bg-paper">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Micro>Request Processing Pipeline</Micro>
          {activeCount > 0 ? (
            <span className="inline-flex items-center gap-1 text-[0.6rem] text-emerald-900">
              <StatusLight tone="emerald" pulse title="Running" />
              {activeCount} running
            </span>
          ) : null}
          {pendingCount > 0 ? (
            <span className="inline-flex items-center gap-1 text-[0.6rem] text-sky-950">
              <StatusLight tone="sky" pulse title="Pending" />
              {pendingCount} pending
            </span>
          ) : null}
        </div>
        <Tabs
          value={viewMode}
          onValueChange={(value) => setViewMode(value as 'bulk' | 'individual')}
        >
          <TabsList className="h-7 shrink-0" aria-label="Pipeline view mode">
            <TabsTrigger value="bulk" className="h-6 px-2 text-[0.65rem]">
              Bulk
            </TabsTrigger>
            <TabsTrigger value="individual" className="h-6 px-2 text-[0.65rem]">
              Individual
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-3 py-1.5">
        <CompactFilterSelect
          label="Intake"
          value={intake}
          onChange={setIntake}
          options={[{ value: 'drop', label: 'drop' }]}
        />
        <CompactFilterSelect
          label="Window"
          value={String(days)}
          onChange={(value) => setDays(Number(value))}
          options={[
            { value: '1', label: '1 day' },
            { value: '7', label: '7 days' },
            { value: '14', label: '14 days' },
            { value: '30', label: '30 days' },
          ]}
        />
        <CompactFilterSelect
          label="Download"
          value={downloadStatus}
          onChange={setDownloadStatus}
          options={[
            { value: '', label: 'Any' },
            { value: 'pending', label: 'pending' },
            { value: 'in_flight', label: 'in_flight' },
            { value: 'success', label: 'success' },
            { value: 'submit_error', label: 'submit_error' },
            { value: 'outcome_error', label: 'outcome_error' },
          ]}
        />
        <CompactFilterSelect
          label="Overall"
          value={overallStatus}
          onChange={setOverallStatus}
          options={[
            { value: '', label: 'Any' },
            { value: 'in_progress', label: 'in_progress' },
            { value: 'complete', label: 'complete' },
            { value: 'needs_attention', label: 'needs_attention' },
          ]}
        />
        {viewMode === 'individual' ? (
          <div
            className="flex flex-wrap items-center gap-1"
            role="group"
            aria-label="Filter individual runs"
          >
            {RUN_STATUS_FILTERS.map((filter) => {
              const selected = runStatusFilter === filter.value
              return (
                <Tooltip key={filter.value || 'all'}>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className={
                        selected
                          ? 'rounded-md bg-habeas-navy px-2 py-0.5 text-[0.6rem] font-medium text-white'
                          : 'rounded-md border border-line bg-paper px-2 py-0.5 text-[0.6rem] text-ink-soft transition-colors hover:border-habeas-navy/40 hover:text-ink'
                      }
                      aria-pressed={selected}
                      onClick={() => setRunStatusFilter(filter.value)}
                    >
                      {filter.label}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>
                    Show {filter.label.toLowerCase()} runs
                  </TooltipContent>
                </Tooltip>
              )
            })}
          </div>
        ) : null}
      </div>

      <div className="min-h-[16rem]">
        {viewMode === 'individual' ? (
          listQuery.isError ? (
            <div className="space-y-2 px-3 py-3">
              <p className="text-xs text-red-700">{errorMessage}</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void listQuery.refetch()}
              >
                Retry
              </Button>
            </div>
          ) : (
            <ProcessRunsHistoryPanel
              stage="download,land,promote,matching"
              processId={selectedProcessId}
              processIds={
                selectedProcessId != null
                  ? undefined
                  : rows.map((row) => row.process_id)
              }
              days={days}
              defaultStatus={runStatusFilter}
              embedded
              hideStatusFilter
              emptyLabel="No individual runs match the current filters."
            />
          )
        ) : listQuery.isError ? (
          <div className="space-y-2 px-3 py-3">
            <p className="text-xs text-red-700">{errorMessage}</p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void listQuery.refetch()}
            >
              Retry
            </Button>
          </div>
        ) : listQuery.isPending && !listQuery.data ? (
          <div className="space-y-2 p-3" role="status" aria-label="Loading batch runs">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="px-3 py-3 text-xs text-ink-soft">
            No bulk processes match the current filters.
          </p>
        ) : (
          <div>
            {rows.map((row) => (
              <BatchProcessExpandRow
                key={row.process_id}
                row={row}
                expanded={expandedId === row.process_id}
                onToggle={() => toggle(row.process_id)}
                focusedStage={
                  expandedId === row.process_id ? focusedStage : undefined
                }
                onStageChange={
                  expandedId === row.process_id ? onStageChange : undefined
                }
                peerProcesses={rows}
                historyDays={Math.min(Math.max(days, 1), 30)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function formatMetricTs(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function CompactOpsMetricsSkeleton() {
  return (
    <div
      className="flex w-full gap-1.5 overflow-x-auto"
      role="status"
      aria-label="Loading ops metrics"
    >
      {Array.from({ length: 6 }, (_, index) => (
        <div
          key={index}
          className="min-w-[5.5rem] flex-1 rounded-md border border-line bg-paper px-1.5 py-1.5"
        >
          <Skeleton className="h-2 w-10" />
          <Skeleton className="mt-2 h-8 w-8 rounded-full" />
        </div>
      ))}
    </div>
  )
}

function MetricSparkBar({
  percent,
  tone = 'navy',
}: {
  percent: number
  tone?: 'navy' | 'emerald' | 'red' | 'amber' | 'sky'
}) {
  const clamped = Math.max(0, Math.min(100, percent))
  const fill =
    tone === 'emerald'
      ? 'bg-emerald-600'
      : tone === 'red'
        ? 'bg-red-600'
        : tone === 'amber'
          ? 'bg-amber-600'
          : tone === 'sky'
            ? 'bg-sky-600'
            : 'bg-habeas-navy'
  return (
    <div className="mt-1.5 flex h-6 items-end gap-px" aria-hidden="true">
      {Array.from({ length: 8 }, (_, index) => {
        const threshold = ((index + 1) / 8) * 100
        const on = clamped >= threshold - 100 / 16
        return (
          <div
            key={index}
            className={`w-1 rounded-sm ${on ? fill : 'bg-line'}`}
            style={{ height: `${28 + index * 8}%` }}
          />
        )
      })}
    </div>
  )
}

function CompactOpsMetrics({
  openRequests,
  reviewPending,
  lastCaDrop,
  nextCaDrop,
  errorRateMonth,
  matchRate,
  matchPending,
  matchDrainActive,
  totalSuppressed,
  workerHealth,
  loading,
}: {
  openRequests: number | null
  reviewPending: number | null
  lastCaDrop: string | null
  nextCaDrop: string | null
  errorRateMonth: number | null
  matchRate: number | null
  matchPending: number | null
  matchDrainActive: boolean | null
  totalSuppressed: number | null
  workerHealth: Record<string, WorkerHealthProbe> | undefined
  loading?: boolean
}) {
  if (loading) return <CompactOpsMetricsSkeleton />

  const workersUp = WORKER_ORDER.filter((name) => workerHealth?.[name]?.ok).length
  const errorPct = errorRateMonth == null ? null : errorRateMonth * 100
  const matchPct = matchRate == null ? null : matchRate * 100

  const cells: {
    key: string
    label: string
    value: string
    viz: ReactNode
    detail: ReactNode
  }[] = [
    {
      key: 'open',
      label: 'Open',
      value: openRequests == null ? '—' : String(openRequests),
      viz: (
        <MiniRing
          percent={Math.min(100, ((openRequests ?? 0) / Math.max(openRequests ?? 1, 20)) * 100)}
          tone="navy"
        />
      ),
      detail: (
        <>
          <p className="text-xs text-ink-soft">
            Review queue <span className="tabular-nums text-ink">{reviewPending ?? '—'}</span>
          </p>
          <Link
            to="/requests/needs-attention"
            className="mt-1 inline-block text-[0.65rem] text-habeas-mid underline-offset-2 hover:underline"
          >
            Open Inbox →
          </Link>
        </>
      ),
    },
    {
      key: 'cadrop',
      label: 'CA DROP',
      value: formatMetricTs(lastCaDrop),
      viz: <MetricSparkBar percent={lastCaDrop ? 72 : 12} tone="navy" />,
      detail: (
        <dl className="space-y-1 text-xs">
          <div className="flex justify-between gap-3">
            <dt className="text-mute">Last success</dt>
            <dd className="tabular-nums text-ink">{formatMetricTs(lastCaDrop)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-mute">Next run</dt>
            <dd className="tabular-nums text-ink">{formatMetricTs(nextCaDrop)}</dd>
          </div>
        </dl>
      ),
    },
    {
      key: 'error',
      label: 'Errors',
      value: errorPct == null ? '—' : `${errorPct.toFixed(1)}%`,
      viz: (
        <MiniRing
          percent={errorPct ?? 0}
          tone={(errorPct ?? 0) > 8 ? 'red' : 'amber'}
        />
      ),
      detail: (
        <p className="text-xs text-ink-soft">
          Failed / total attempts over the last ~90 days from worker trends.
        </p>
      ),
    },
    {
      key: 'match',
      label: 'Match',
      value: matchPct == null ? '—' : `${matchPct.toFixed(0)}%`,
      viz: <MiniRing percent={matchPct ?? 0} tone="emerald" />,
      detail: (
        <p className="text-xs text-ink-soft">
          Success vs pending matching attempts · queue{' '}
          <span className="tabular-nums text-ink">{matchPending ?? '—'}</span>
          {matchDrainActive ? (
            <>
              {' '}
              · <span className="text-habeas-mid">drain active</span>
            </>
          ) : null}
        </p>
      ),
    },
    {
      key: 'suppressed',
      label: 'Suppressed',
      value: totalSuppressed == null ? '—' : String(totalSuppressed),
      viz: <MetricSparkBar percent={Math.min(100, (totalSuppressed ?? 0) / 10)} tone="emerald" />,
      detail: (
        <p className="text-xs text-ink-soft">
          DROP rows with response_status 3 / 4 / 5 (deleted, opted out, not found).
        </p>
      ),
    },
    {
      key: 'health',
      label: 'Health',
      value: `${workersUp}/${WORKER_ORDER.length}`,
      viz: (
        <MiniRing
          percent={(workersUp / WORKER_ORDER.length) * 100}
          tone={workersUp === WORKER_ORDER.length ? 'emerald' : 'red'}
        />
      ),
      detail: (
        <ul className="space-y-0.5 text-[0.65rem]">
          {WORKER_ORDER.map((name) => {
            const probe = workerHealth?.[name]
            const ok = probe?.ok === true
            return (
              <li key={name} className="flex items-center justify-between gap-2">
                <span className="font-mono text-ink-soft">{name}</span>
                <span className={ok ? 'text-emerald-700' : 'text-red-700'}>
                  {probe == null ? '—' : ok ? 'up' : 'down'}
                </span>
              </li>
            )
          })}
        </ul>
      ),
    },
  ]

  return (
    <div className="flex w-full gap-1.5 overflow-x-auto pb-0.5">
      {cells.map((cell) => (
        <MetricHoverCard
          key={cell.key}
          label={cell.label}
          value={cell.value}
          viz={cell.viz}
          detail={cell.detail}
        />
      ))}
    </div>
  )
}

function MetricHoverCard({
  label,
  value,
  viz,
  detail,
}: {
  label: string
  value: string
  viz: ReactNode
  detail: ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="min-w-[5.5rem] flex-1 rounded-md border border-line bg-paper px-1.5 py-1.5 text-left transition-colors hover:border-habeas-navy/35 hover:bg-panel/40"
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
        >
          <p className="text-[0.5rem] font-medium uppercase tracking-wide text-mute">
            {label}
          </p>
          <div className="mt-1 flex items-center gap-1.5">
            {viz}
            <p className="min-w-0 truncate text-sm font-semibold tabular-nums text-ink">
              {value}
            </p>
          </div>
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-64 p-3"
        side="bottom"
        align="start"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
          {label}
        </p>
        <p className="mt-1 text-lg font-semibold tabular-nums text-ink">{value}</p>
        <div className="mt-2">{detail}</div>
      </PopoverContent>
    </Popover>
  )
}

function RunPipelineButton({
  disabled,
  onQueued,
  focusResultPanel,
}: {
  disabled?: boolean
  onQueued: (label: string, result: unknown) => void
  focusResultPanel: () => void
}) {
  const queryClient = useQueryClient()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [phase, setPhase] = useState<string | null>(null)

  const runMutation = useMutation({
    mutationFn: async () => {
      setPhase('Queuing CA DROP download…')
      const download = await postDropDownload()
      setPhase('Queuing land (unzip)…')
      const land = await postDropLand()
      setPhase('Queuing promote to raw…')
      const promote = await postDropPromote()
      return { download, land, promote }
    },
    onSuccess: (payload) => {
      setPhase(null)
      setConfirmOpen(false)
      onQueued('Run Pipeline · CA DROP', payload)
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-processes'] })
    },
    onError: () => {
      setPhase(null)
    },
  })

  function confirmRun() {
    void actionToast.promise(runMutation.mutateAsync(), {
      id: DROP_PIPELINE_RUN_TOAST_ID,
      loading: 'Queuing CA DROP pipeline…',
      success: () => ({
        title: 'Pipeline queued',
        description: 'Download, land, and promote were queued.',
        action: {
          label: 'View result',
          onClick: focusResultPanel,
        },
      }),
      error: () => ({
        title: 'Pipeline queue failed',
        action: {
          label: 'Retry',
          onClick: confirmRun,
        },
      }),
    })
  }

  return (
    <>
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                size="sm"
                className="gap-1.5"
                disabled={disabled || runMutation.isPending}
              >
                <PlayPipelineIcon className="h-3.5 w-3.5" />
                {runMutation.isPending ? 'Running…' : 'Run Pipeline'}
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>Start an intake pipeline run</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel>Intake type</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => {
              setConfirmOpen(true)
            }}
          >
            <span className="flex flex-col gap-0.5">
              <span className="font-medium text-ink">CA DROP</span>
              <span className="text-[0.65rem] text-mute">
                Download → Land → Promote
              </span>
            </span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => {
          if (!open && runMutation.isPending) return
          setConfirmOpen(open)
        }}
      >
        {/* No `relative`: twMerge would override DialogContent `fixed` and park the modal at page bottom. */}
        <DialogContent className="max-w-md overflow-hidden">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-1 overflow-hidden bg-panel">
            <div
              className={`h-full bg-habeas-navy transition-all duration-500 ${
                runMutation.isPending ? 'w-2/3 animate-pulse' : confirmOpen ? 'w-1/4' : 'w-0'
              }`}
            />
          </div>
          <DialogHeader>
            <DialogTitle>Run CA DROP pipeline?</DialogTitle>
            <DialogDescription>
              Queues download, land, and promote through admin-api. The connector can take up
              to ~2 minutes before a bulk card appears.
            </DialogDescription>
          </DialogHeader>
          <ol className="space-y-1.5 text-xs text-ink-soft">
            {['Download ZIP', 'Land (unzip)', 'Promote to raw'].map((step, index) => (
              <li
                key={step}
                className="flex items-center gap-2 rounded-md border border-line/80 bg-panel/40 px-2 py-1.5"
              >
                <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-paper text-[0.6rem] font-medium text-mute">
                  {index + 1}
                </span>
                {step}
              </li>
            ))}
          </ol>
          {phase ? (
            <p className="text-xs text-habeas-navy" role="status" aria-live="polite">
              {phase}
            </p>
          ) : null}
          <DialogFooter>
            <button
              type="button"
              className="taste-btn px-3 py-1.5 text-xs"
              disabled={runMutation.isPending}
              onClick={() => setConfirmOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="taste-btn-primary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs"
              disabled={runMutation.isPending}
              onClick={confirmRun}
            >
              <PlayPipelineIcon className="h-3.5 w-3.5" />
              {runMutation.isPending ? 'Queuing…' : 'Confirm & run'}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}


function StatusCountTable({
  rows,
  empty,
}: {
  rows: { status: string; count: number }[]
  empty: string
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-ink-soft">{empty}</p>
  }
  return (
    <table className="taste-table">
      <thead>
        <tr>
          <th className="!px-0">Status</th>
          <th className="!px-0">Count</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.status}>
            <td className="!px-0 font-mono text-xs">{row.status}</td>
            <td className="!px-0 tabular-nums">{row.count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function countForResponseStatus(
  rows: { response_status: number | null; count: number }[] | undefined,
  value: number | null,
): number {
  if (!rows) return 0
  return rows
    .filter((row) => row.response_status === value)
    .reduce((sum, row) => sum + row.count, 0)
}

function HashIndexPanel({
  data,
  showSkeleton,
  hashState,
  setHashState,
  hashPending,
  hashWorkerDown,
  lastRun,
  onHashRefresh,
  hashRefreshPending,
  actionMutation,
}: {
  data: DropPipelineStatus | undefined
  showSkeleton: boolean
  hashState: string
  setHashState: (state: string) => void
  hashPending: boolean
  hashWorkerDown: boolean
  lastRun: HashIndexRefreshStatus['last_run']
  onHashRefresh: (
    action: { kind: 'refresh-state'; state: string } | { kind: 'refresh-all' },
  ) => void
  hashRefreshPending: boolean
  actionMutation: { isPending: boolean }
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-line bg-paper p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <Micro>Hash index refresh</Micro>
            <p className="mt-1 max-w-xl text-xs text-ink-soft">
              Enqueues then processes a dbt rebuild per state, then rematches open not-found /
              multi-match DROP rows for that state.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <label className="flex items-center gap-1.5 text-xs text-ink-soft">
              <span className="taste-micro">State</span>
              <select
                className="rounded-md border border-line bg-paper px-2 py-1 font-mono text-xs text-ink"
                value={hashState}
                onChange={(event) => setHashState(event.target.value)}
                aria-label="Hash index refresh state"
              >
                {SERVED_STATE_ACRONYMS.map((state) => (
                  <option key={state} value={state}>
                    {state}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="taste-btn-primary px-3 py-1.5 text-xs"
              disabled={
                showSkeleton ||
                hashPending ||
                hashRefreshPending ||
                actionMutation.isPending
              }
              onClick={() => onHashRefresh({ kind: 'refresh-state', state: hashState })}
            >
              Refresh state
            </button>
            <button
              type="button"
              className="taste-btn px-3 py-1.5 text-xs"
              disabled={
                showSkeleton ||
                hashPending ||
                hashRefreshPending ||
                actionMutation.isPending
              }
              onClick={() => onHashRefresh({ kind: 'refresh-all' })}
            >
              Refresh all
            </button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-3 text-xs text-ink-soft">
          <span>
            {hashWorkerDown
              ? 'Worker down'
              : hashPending
                ? 'Pending / in-flight'
                : lastRun
                  ? `Last ${lastRun.status}`
                  : 'No runs yet'}
          </span>
          {lastRun?.status === 'success' ? (
            <span>
              rows e/p/n {lastRun.rows_email ?? '—'}/{lastRun.rows_phone ?? '—'}/
              {lastRun.rows_ndz ?? '—'} · rematch {lastRun.rematch_enqueued_count}
            </span>
          ) : null}
          {lastRun?.status && lastRun.status !== 'success' && lastRun.error_message ? (
            <span className="text-red-700">{lastRun.error_message}</span>
          ) : null}
        </div>
        <div className="mt-3">
          <StatusCountTable
            rows={data?.hash_index_refresh?.attempts_by_status ?? []}
            empty="No hash-index refresh attempts yet."
          />
        </div>
      </div>
      <HashRefreshRunsPanel />
    </div>
  )
}

function HashRefreshRunsPanel() {
  const runsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'hash-refresh-runs'],
    queryFn: () => listRuns({ job: 'hash_index_refresh', limit: 40 }),
    refetchInterval: 5_000,
    placeholderData: (previous) => previous,
  })
  const runs = runsQuery.data ?? []
  return (
    <div className="rounded-md border border-line bg-paper">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <Micro>Hash refresh run history</Micro>
        <Link
          to="/ops/runs"
          search={runsSearchForWorker('hash_index_refresh')}
          className="text-[0.65rem] text-habeas-mid hover:underline"
        >
          Runs →
        </Link>
      </div>
      {runs.length === 0 ? (
        <p className="px-3 py-3 text-xs text-ink-soft">No hash refresh attempts yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="taste-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>Age</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id}>
                  <td className="font-mono text-xs">
                    <Link
                      to="/ops/runs/$job/$attemptId"
                      params={{
                        job: run.job,
                        attemptId: String(run.attempt_number),
                      }}
                      className="text-habeas-mid underline-offset-2 hover:underline"
                    >
                      {run.run_id}
                    </Link>
                  </td>
                  <td className="text-xs">{run.status.replaceAll('_', ' ')}</td>
                  <td className="tabular-nums text-xs text-ink-soft">
                    {runAgeLabel(run.started_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function DropPipelinePage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <DropPipelinePageInner />
    </RoleGate>
  )
}

function DropPipelinePageInner() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { tab, process: processId, stage: focusedStage } = useSearch({ from: '/' })
  const [lastAction, setLastAction] = useState<string | null>(null)
  const [actionResult, setActionResult] = useState<string | null>(null)
  const [hashState, setHashState] = useState('CA')
  const actionResultRef = useRef<HTMLDivElement>(null)

  function focusActionResultPanel(targetTab: PipelineTab = 'pipeline') {
    const focusPanel = () => {
      const el = actionResultRef.current
      if (!el) return
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      el.focus({ preventScroll: true })
    }
    if (tab !== targetTab) {
      void navigate({
        to: '/',
        search: { tab: targetTab, process: processId, stage: focusedStage },
      }).then(() => {
        requestAnimationFrame(() => requestAnimationFrame(focusPanel))
      })
      return
    }
    requestAnimationFrame(focusPanel)
  }

  function setTab(next: PipelineTab) {
    void navigate({
      to: '/',
      search: { tab: next, process: processId, stage: focusedStage },
    })
  }

  function setProcess(next: number | undefined) {
    void navigate({
      to: '/',
      search: { tab, process: next, stage: focusedStage },
      replace: true,
    })
  }

  function setStage(next: PipelineStageTab) {
    void navigate({
      to: '/',
      search: { tab, process: processId, stage: next },
      replace: true,
    })
  }

  const pipelineQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-pipeline'],
    queryFn: getDropPipeline,
    refetchInterval: 5_000,
    placeholderData: (previous) => previous,
  })

  const processesQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-processes', 'recent-30d'],
    // Prefer recent window (not calendar "today") so older downloads still surface.
    queryFn: () => listDropBulkProcesses({ days: 30, limit: 100 }),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const processList = processesQuery.data?.processes ?? []

  // Auto-select only a recent process (48h) — older downloads are History/Inspect.
  useEffect(() => {
    if (processId != null) return
    const recent = processList.find((process) => {
      if (!process.process_at) return false
      const ageMs = Date.now() - new Date(process.process_at).getTime()
      return ageMs >= 0 && ageMs <= ACTIVE_BULK_MAX_AGE_MS
    })
    if (recent != null) setProcess(recent.process_id)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only auto-select when list arrives
  }, [processId, processList])

  // Drop URL process ids that are no longer in the recent list.
  useEffect(() => {
    if (processId == null || processList.length === 0) return
    if (processList.some((item) => item.process_id === processId)) return
    setProcess(undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processId, processList])

  const trendsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-workers', 'trends', '3m'],
    queryFn: () => getDropWorkerTrends('3m'),
    refetchInterval: 60_000,
    placeholderData: (previous) => previous,
  })

  const actionMutation = useMutation({
    mutationFn: async (key: ActionKey) => {
      const action = ACTIONS.find((item) => item.key === key)
      if (!action) throw new Error(`unknown action ${key}`)
      return { key, data: await action.run() }
    },
    onMutate: (key) => {
      const action = ACTIONS.find((item) => item.key === key)
      setLastAction(action?.label ?? key)
      setActionResult('__pending__')
      requestAnimationFrame(() => {
        actionResultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      })
    },
    onSuccess: ({ key, data }) => {
      setActionResult(JSON.stringify(data, null, 2))
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-processes'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'approvals'] })
      const label = ACTIONS.find((item) => item.key === key)?.label ?? 'Action'
      actionToast.success({
        title: `${label} queued`,
        description: 'Response is in the result panel.',
        action: {
          label: 'View result',
          onClick: () => focusActionResultPanel('pipeline'),
        },
      })
    },
    onError: (error, key) => {
      setActionResult(error instanceof Error ? error.message : String(error))
      const label = ACTIONS.find((item) => item.key === key)?.label ?? 'Action'
      actionToast.error({
        title: `${label} failed`,
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => actionMutation.mutate(key),
        },
      })
    },
  })

  const hashIndexMutation = useMutation({
    mutationFn: async (
      action: { kind: 'refresh-state'; state: string } | { kind: 'refresh-all' },
    ) => {
      if (action.kind === 'refresh-state') {
        setLastAction(`Refresh hash index (${action.state})`)
        setActionResult('__pending__')
        const enqueue = await postHashIndexRefreshEnqueue({ state: action.state })
        const process = await postHashIndexRefreshProcess()
        return { enqueue, process }
      }
      setLastAction('Refresh hash index (all states)')
      setActionResult('__pending__')
      const enqueue = await postHashIndexRefreshEnqueueAll()
      const process = await postHashIndexRefreshProcess()
      return { enqueue, process }
    },
    onSuccess: (payload) => {
      setActionResult(JSON.stringify(payload, null, 2))
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-processes'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-stats-global'] })
    },
    onError: (error) => {
      setActionResult(error instanceof Error ? error.message : String(error))
    },
  })

  function runHashRefresh(
    action: { kind: 'refresh-state'; state: string } | { kind: 'refresh-all' },
  ) {
    void actionToast.promise(hashIndexMutation.mutateAsync(action), {
      id: DROP_HASH_REFRESH_TOAST_ID,
      loading: 'Queuing hash index refresh…',
      success: () => ({
        title: 'Hash refresh queued',
        description: 'Enqueue and process steps completed.',
        action: {
          label: 'View result',
          onClick: () => focusActionResultPanel('hash_refresh'),
        },
      }),
      error: () => ({
        title: 'Hash refresh failed',
        action: {
          label: 'Retry',
          onClick: () => runHashRefresh(action),
        },
      }),
    })
  }

  const data: DropPipelineStatus | undefined = pipelineQuery.data
  const showSkeleton = pipelineQuery.isPending && !data
  const hashPending = (data?.hash_index_refresh?.pending ?? 0) > 0
  const hashWorkerDown = data ? !data.worker_health.hash_index_refresh?.ok : false
  const lastRun = data?.hash_index_refresh?.last_run
  const caSchedule = data?.ca_drop_schedule

  const monthErrorRate = (() => {
    const rows = trendsQuery.data?.workers ?? []
    let failed = 0
    let total = 0
    for (const row of rows) {
      failed += row.current.failed
      total += row.current.total
    }
    if (total <= 0) return null
    return failed / total
  })()

  const matchPending = data?.matching_attempts.pending ?? null
  const matchSuccess = data?.matching_attempts.success ?? null
  const matchDrainActive = data?.matching_attempts.drain?.active ?? null
  const matchRate =
    matchPending != null && matchSuccess != null && matchPending + matchSuccess > 0
      ? matchSuccess / (matchSuccess + matchPending)
      : null

  const totalSuppressed =
    data?.fulfillment?.by_response_status != null
      ? [3, 4, 5].reduce(
          (sum, code) =>
            sum + countForResponseStatus(data.fulfillment?.by_response_status, code),
          0,
        )
      : null

  return (
    <TooltipProvider delayDuration={250}>
    <section className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">Pipeline</p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight text-ink">Console</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {pipelineQuery.isFetching && !pipelineQuery.isPending ? (
            <span className="rounded-md border border-line px-2 py-0.5 text-[0.65rem] text-mute">
              Refreshing
            </span>
          ) : null}
          <Link
            to="/ops/workers/settings"
            className="taste-btn inline-flex h-9 w-9 items-center justify-center p-0"
            aria-label="Settings"
            title="Settings"
          >
            <svg
              viewBox="0 0 24 24"
              className="size-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" />
              <path d="M19.4 13.5a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V19a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H5a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01A1.7 1.7 0 0 0 11 5.09V5a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55h.01a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01a1.7 1.7 0 0 0 1.55 1H19a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1Z" />
            </svg>
          </Link>
          <RunPipelineButton
            disabled={showSkeleton}
            focusResultPanel={() => focusActionResultPanel('pipeline')}
            onQueued={(label, result) => {
              setLastAction(label)
              setActionResult(JSON.stringify(result, null, 2))
            }}
          />
        </div>
      </header>

      <CompactOpsMetrics
        loading={showSkeleton}
        openRequests={data?.drop_requests.count ?? null}
        reviewPending={data?.matching_review.pending ?? null}
        lastCaDrop={caSchedule?.last_success_at ?? null}
        nextCaDrop={caSchedule?.next_run_at ?? null}
        errorRateMonth={monthErrorRate}
        matchRate={matchRate}
        matchPending={matchPending}
        matchDrainActive={matchDrainActive}
        totalSuppressed={totalSuppressed}
        workerHealth={data?.worker_health}
      />

      {lastAction && actionResult && tab === 'pipeline' ? (
        <div ref={actionResultRef} tabIndex={-1} className="outline-none">
          <ActionResultFrame
            lastAction={lastAction}
            actionResult={actionResult}
            onClear={() => {
              setLastAction(null)
              setActionResult(null)
            }}
          />
        </div>
      ) : null}

      <PipelineTabBar active={tab} onSelect={setTab} />

      {pipelineQuery.isError && !data && (
        <p className="text-sm text-red-700">
          Could not load DROP pipeline status from admin-api.
        </p>
      )}

      {tab === 'pipeline' ? (
        <BatchRequestRunsList
          selectedProcessId={processId}
          focusedStage={focusedStage}
          onSelectProcess={(id) => setProcess(id)}
          onStageChange={setStage}
        />
      ) : null}

      {tab === 'history' ? (
        <ProcessRunsHistoryPanel
          key={`history:${processId ?? 'all'}`}
          stage="download,land,promote,matching"
          processId={processId}
          days={30}
          defaultStatus="attention"
          emptyLabel="No open or failed runs in the selected window."
        />
      ) : null}

      {tab === 'errors' ? <OpsLogExplorer mode="errors" /> : null}

      {tab === 'logs' ? <OpsLogExplorer mode="logs" /> : null}

      {tab === 'hash_refresh' && (
        <HashIndexPanel
          data={data}
          showSkeleton={showSkeleton}
          hashState={hashState}
          setHashState={setHashState}
          hashPending={hashPending}
          hashWorkerDown={hashWorkerDown}
          lastRun={lastRun ?? null}
          onHashRefresh={runHashRefresh}
          hashRefreshPending={hashIndexMutation.isPending}
          actionMutation={actionMutation}
        />
      )}

      {tab === 'hash_refresh' && lastAction && actionResult ? (
        <div ref={actionResultRef} tabIndex={-1} className="outline-none">
          <ActionResultFrame
            lastAction={lastAction}
            actionResult={actionResult}
            onClear={() => {
              setLastAction(null)
              setActionResult(null)
            }}
          />
        </div>
      ) : null}
    </section>
    </TooltipProvider>
  )
}
