import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { Skeleton, SkeletonLines } from '@/components/AppShell'
import { Button } from '@/components/ui/button'
import {
  ConfirmActionDialog,
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
import { RoleGate, isSuperAdmin, useMe } from '@/lib/auth'
import { cn } from '@/lib/utils'
import {
  getDropBulkProcess,
  getDropPipeline,
  getDropWorkerTrends,
  getDropWorkers,
  listDropBulkProcesses,
  listDropBulkProcessRuns,
  listRuns,
  postDropDownload,
  postDropFulfill,
  postDropLand,
  postDropMatch,
  postDropPromote,
  postDropWorkflowAssign,
  postHashIndexRefreshEnqueue,
  postHashIndexRefreshEnqueueAll,
  postHashIndexRefreshProcess,
  type BulkProcessDetail,
  type BulkProcessRun,
  type BulkProcessRunGroup,
  type BulkProcessStageCounts,
  type BulkProcessSummary,
  type BulkProcessesPayload,
  type DropPipelineStatus,
  type HashIndexRefreshStatus,
  type StepStatusCount,
  type WorkerHealthProbe,
} from '@/lib/api'
import { RetryConfigPanel } from '@/routes/ops/health/configuration'
import {
  runsSearchForWorker,
  type PipelineStageTab,
  type PipelineTab,
} from '@/router'

const RUNS_PAGE_SIZE = 10

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
] as const

const PIPELINE_TAB_BAR: { key: PipelineTab; label: string }[] = [
  { key: 'pipeline', label: 'Pipeline' },
  { key: 'hash_refresh', label: 'Hash refresh' },
  { key: 'history', label: 'History' },
  { key: 'configurations', label: 'Configurations' },
]

type BulkPipelineStageKey = keyof BulkProcessDetail['stages']

const STAGE_KEY_LABELS: Record<BulkPipelineStageKey, string> = {
  download: 'Download',
  land: 'Land',
  promote: 'Promote',
  matching: 'Matching',
  review: 'Review',
  fulfillment: 'Fulfill',
}

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
    stages: [
      { key: 'matching', label: 'Matching' },
      { key: 'review', label: 'Review' },
    ],
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

function stageCardClassName(visual: StageVisual): string {
  switch (visual) {
    case 'complete':
      return 'border-emerald-600/45 bg-emerald-50 text-emerald-950'
    case 'active':
      return 'border-habeas-navy/45 bg-habeas-navy/8'
    case 'failed':
      return 'border-red-400/50 bg-red-50'
    case 'pending':
      return 'border-amber-400/45 bg-amber-50/70'
    default:
      return 'border-line/80 bg-paper'
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

const OPEN_RUN_STATUSES = new Set(['pending', 'claimed', 'in_flight'])
const FAILED_RUN_STATUSES = new Set([
  'submit_error',
  'outcome_error',
  'timeout',
  'abandoned',
])

function filterRunGroupsForStatus(
  groups: BulkProcessRunGroup[],
  statusFilter: string,
): BulkProcessRunGroup[] {
  if (!statusFilter || statusFilter === 'attention') {
    const allowed =
      statusFilter === 'attention'
        ? new Set([...OPEN_RUN_STATUSES, ...FAILED_RUN_STATUSES])
        : null
    if (!allowed) return groups
    return groups
      .map((group) => {
        const runs = group.runs.filter((run) => allowed.has(run.status))
        return { ...group, runs, run_count: runs.length }
      })
      .filter((group) => group.run_count > 0)
  }
  return groups.filter((group) => group.run_count > 0)
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
      statusFilter,
    ],
    queryFn: async () => {
      // Fetch unfiltered for "attention" so older admin-api builds still work;
      // filter open+failed client-side. Named filters still hit the API.
      const apiStatus =
        !statusFilter || statusFilter === 'attention' ? undefined : statusFilter
      const payload = await listDropBulkProcessRuns({
        stage,
        days,
        process_id: processId,
        status: apiStatus,
      })
      if (statusFilter !== 'attention') return payload
      return {
        ...payload,
        groups: filterRunGroupsForStatus(payload.groups, 'attention'),
      }
    },
    refetchInterval: 5_000,
    placeholderData: (previous) => previous,
  })

  const allowed =
    processIds != null ? new Set(processIds) : null
  const groups = (runsQuery.data?.groups ?? []).filter((group) => {
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

function bulkDurationLabel(
  processAt: string | null | undefined,
  completedAt?: string | null,
): string | null {
  if (!processAt) return null
  const start = new Date(processAt).getTime()
  if (Number.isNaN(start)) return null
  const end = completedAt ? new Date(completedAt).getTime() : Date.now()
  if (Number.isNaN(end) || end < start) return null
  const minutes = Math.floor((end - start) / 60_000)
  if (minutes < 60) return `${Math.max(minutes, 0)}m`
  const hours = Math.floor(minutes / 60)
  const rem = minutes % 60
  if (hours < 48) return rem > 0 ? `${hours}h ${rem}m` : `${hours}h`
  const days = Math.floor(hours / 24)
  const dayRem = hours % 24
  return dayRem > 0 ? `${days}d ${dayRem}h` : `${days}d`
}

function bulkStageLabel(stageKey: string | undefined): string {
  if (!stageKey) return '—'
  if (stageKey in STAGE_KEY_LABELS) {
    return STAGE_KEY_LABELS[stageKey as BulkPipelineStageKey]
  }
  return stageKey.replaceAll('_', ' ')
}

function stageRunIndicators(counts: BulkProcessStageCounts | undefined): {
  finished: number
  queued: number
  failed: number
  abandoned: number
  percent: number
} {
  if (!counts || counts.total <= 0) {
    return { finished: 0, queued: 0, failed: 0, abandoned: 0, percent: 0 }
  }
  const abandoned =
    counts.by_list_type
      ?.filter((row) => row.status.toLowerCase() === 'abandoned')
      .reduce((sum, row) => sum + row.count, 0) ??
    (counts.other ?? 0)
  const failed = Math.max(0, counts.failed - abandoned)
  return {
    finished: counts.success,
    queued: counts.open,
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

function RunningPulse({ label = 'Running' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded border border-emerald-300/70 bg-emerald-50/90 px-1.5 py-0.5 text-[0.6rem] font-medium uppercase tracking-wide text-emerald-900">
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-600" />
      </span>
      {label}
    </span>
  )
}

function PendingPulse({ label = 'Pending' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded border border-sky-300/70 bg-sky-50/90 px-1.5 py-0.5 text-[0.6rem] font-medium uppercase tracking-wide text-sky-950">
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-pulse rounded-full bg-sky-400 opacity-70" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-sky-600" />
      </span>
      {label}
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

function retryCountFromRuns(runs: { attempt_number: number }[]): number {
  return runs.reduce((sum, run) => sum + Math.max(0, run.attempt_number - 1), 0)
}

function StageRunStatChips({
  finished,
  queued,
  failed,
  abandoned,
  dense = false,
}: {
  finished: number
  queued: number
  failed: number
  abandoned: number
  dense?: boolean
}) {
  const chip = dense
    ? 'inline-flex items-center gap-1 rounded px-1 py-px text-[0.55rem] tabular-nums'
    : 'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[0.6rem] tabular-nums'
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className={`${chip} bg-emerald-50 text-emerald-900`}>
        <span className="text-mute">Finished</span> {finished}
      </span>
      <span className={`${chip} bg-sky-50 text-sky-950`}>
        <span className="text-mute">Queued</span> {queued}
      </span>
      <span
        className={`${chip} ${failed > 0 ? 'bg-red-50 text-red-800' : 'bg-panel text-ink-soft'}`}
      >
        <span className="text-mute">Failed</span> {failed}
      </span>
      <span
        className={`${chip} ${abandoned > 0 ? 'bg-amber-50 text-amber-950' : 'bg-panel text-ink-soft'}`}
      >
        <span className="text-mute">Abandoned</span> {abandoned}
      </span>
    </div>
  )
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
}: {
  detail: BulkProcessDetail | undefined
  loading?: boolean
  duration?: string | null
  running?: boolean
  activeTab: PipelineStageTab
  onSelectTab: (tab: PipelineStageTab) => void
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
              className="h-10 min-w-[4.5rem] flex-1 rounded border border-line/70 bg-paper/80 px-1.5 py-1"
            >
              <Skeleton className="h-full w-full" />
            </div>
          )
        }
        const counts = countsForStageTab(detail, tab)
        const isCurrent = isStageTabCurrent(detail, tab)
        const selected = activeTab === tab.key
        const visual = stageVisualState(counts, isCurrent)
        const indicators = stageRunIndicators(counts)
        const emphasize = selected || isCurrent

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
              className={`flex min-w-[4.75rem] shrink-0 flex-col items-start justify-center rounded border px-1.5 py-1 text-left transition-colors hover:border-habeas-navy/35 ${stageCardClassName(visual)}`}
              title={
                counts
                  ? `${tab.label}: ${stageCountsBlurb(counts)}`
                  : tab.label
              }
            >
              <p
                className={`text-[0.55rem] font-medium uppercase leading-tight tracking-wide ${
                  visual === 'complete' ? 'text-emerald-800' : 'text-mute'
                }`}
              >
                {tab.label}
              </p>
              <p className="mt-0.5 text-[0.6rem] tabular-nums leading-none text-ink">
                {counts && counts.total > 0 ? `${indicators.percent}%` : '—'}
              </p>
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
            className={`min-w-[13rem] flex-1 rounded-md border px-2.5 py-2 text-left transition-shadow ${stageCardClassName(visual)} ${
              selected ? 'ring-1 ring-habeas-navy/30' : ''
            }`}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-[0.65rem] font-semibold uppercase tracking-wide text-ink">
                  {tab.label}
                  {isCurrent ? (
                    <span className="ml-1.5 font-normal normal-case text-mute">
                      · current
                    </span>
                  ) : null}
                </p>
                <p className="mt-0.5 text-[0.65rem] tabular-nums text-ink-soft">
                  {duration
                    ? `${duration}${running ? ' so far' : ''}`
                    : 'Duration —'}
                </p>
              </div>
              <span className="tabular-nums text-sm font-medium text-ink">
                {indicators.percent}%
              </span>
            </div>
            <div className="relative mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/70">
              <div
                className={
                  visual === 'failed'
                    ? 'h-full rounded-full bg-red-600 transition-[width]'
                    : running && isCurrent
                      ? 'h-full rounded-full bg-emerald-600 transition-[width]'
                      : 'h-full rounded-full bg-habeas-navy transition-[width]'
                }
                style={{ width: `${indicators.percent}%` }}
              />
              {running && isCurrent ? (
                <div className="pointer-events-none absolute inset-0 animate-pulse bg-gradient-to-r from-transparent via-white/40 to-transparent" />
              ) : null}
            </div>
            <div className="mt-1.5">
              <StageRunStatChips
                finished={indicators.finished}
                queued={indicators.queued}
                failed={indicators.failed}
                abandoned={indicators.abandoned}
                dense
              />
            </div>
          </button>
        )
      })}
    </div>
  )
}

function stageTabFromOverall(
  current: string | undefined | null,
): PipelineStageTab {
  const stage = (current ?? '').toLowerCase()
  if (stage === 'download') return 'download'
  if (stage === 'land' || stage === 'promote') return 'ingest'
  if (stage === 'matching' || stage === 'review') return 'matching'
  if (stage === 'fulfillment' || stage === 'fulfill') return 'fulfillment'
  return 'download'
}

async function rerunBulkProcessRun(run: BulkProcessRun) {
  const step = run.step.toLowerCase()
  const job = run.job.toLowerCase()
  if (job === 'drop_connector' || step === 'download') {
    return postDropDownload()
  }
  if (step === 'land') {
    return postDropLand({ land_attempt_id: run.attempt_id })
  }
  if (step === 'promote') {
    return postDropPromote({ promote_attempt_id: run.attempt_id })
  }
  if (job === 'matching' || step === 'matching') {
    return postDropMatch()
  }
  if (job === 'data_fulfillment' || step === 'fulfill' || step === 'fulfillment') {
    if (!run.request_id) throw new Error('Fulfill re-run needs a request id')
    return postDropFulfill({ request_id: run.request_id })
  }
  throw new Error(`No re-run action for ${run.job}/${run.step}`)
}

function BatchProcessExpandRow({
  row,
  expanded,
  onToggle,
  focusedStage,
  onStageChange,
}: {
  row: BulkProcessSummary
  expanded: boolean
  onToggle: () => void
  focusedStage?: PipelineStageTab
  onStageChange?: (stage: PipelineStageTab) => void
}) {
  const { data: me } = useMe()
  const queryClient = useQueryClient()
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
  const [stageTab, setStageTab] = useState<PipelineStageTab>(
    focusedStage ?? stageTabFromOverall(row.overall?.current_stage) ?? 'download',
  )
  const activeStage =
    BULK_CARD_STAGE_TABS.find((tab) => tab.key === stageTab) ?? BULK_CARD_STAGE_TABS[0]
  const runsQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'drop-process-runs',
      'bulk-card',
      row.process_id,
      activeStage.runStage,
    ],
    queryFn: () =>
      listDropBulkProcessRuns({
        stage: activeStage.runStage,
        days: 30,
        process_id: row.process_id,
      }),
    enabled: expanded,
    refetchInterval: expanded ? 5_000 : false,
    placeholderData: (previous) => previous,
  })
  const [runStatusFilter, setRunStatusFilter] = useState('attention')
  const [runPage, setRunPage] = useState(0)
  const [selectedRunIds, setSelectedRunIds] = useState<Set<string>>(new Set())
  const [detailRun, setDetailRun] = useState<BulkProcessRun | null>(null)
  const [assignOpen, setAssignOpen] = useState(false)
  const [assignEmail, setAssignEmail] = useState('')
  const [rerunConfirmOpen, setRerunConfirmOpen] = useState(false)

  const detail = detailQuery.data
  const running = isActiveBulkSummary(row) || isActiveBulkDetail(detail)
  const pending = !running && isPendingBulkSummary(row)
  const percent = detail?.overall.percent ?? row.overall?.percent
  const resolvedStatusKey =
    detail?.overall.status ?? row.overall?.status ?? row.download_status
  const status = resolvedStatusKey.replaceAll('_', ' ')
  const currentStageKey = detail?.overall.current_stage ?? row.overall?.current_stage
  const currentStage = bulkStageLabel(currentStageKey)
  const requestRows = detail?.request_rows ?? row.request_rows
  const completedAt = detail?.completed_at ?? row.completed_at
  const duration = bulkDurationLabel(row.process_at, running ? null : completedAt)
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

  const allRuns = runsQuery.data?.groups.flatMap((group) => group.runs) ?? []
  const filteredRuns = useMemo(() => {
    if (runStatusFilter === 'attention') {
      return allRuns.filter((run) => {
        const s = run.status.toLowerCase()
        return (
          s.includes('fail') ||
          s.includes('error') ||
          s === 'pending' ||
          s === 'claimed' ||
          s === 'in_flight' ||
          s === 'leased' ||
          s === 'abandoned'
        )
      })
    }
    if (runStatusFilter === 'abandoned') {
      return allRuns.filter((run) => run.status.toLowerCase() === 'abandoned')
    }
    if (runStatusFilter === 'pending') {
      return allRuns.filter((run) => {
        const s = run.status.toLowerCase()
        return (
          s === 'pending' || s === 'claimed' || s === 'in_flight' || s === 'leased'
        )
      })
    }
    if (runStatusFilter === 'fail') {
      return allRuns.filter((run) => {
        const s = run.status.toLowerCase()
        return (
          (s.includes('fail') || s.includes('error') || s === 'timeout') &&
          s !== 'abandoned'
        )
      })
    }
    if (runStatusFilter === '') return allRuns
    return allRuns.filter((run) =>
      run.status.toLowerCase().includes(runStatusFilter.toLowerCase()),
    )
  }, [allRuns, runStatusFilter])

  const pageCount = Math.max(1, Math.ceil(filteredRuns.length / RUNS_PAGE_SIZE))
  const safePage = Math.min(runPage, pageCount - 1)
  const pagedRuns = filteredRuns.slice(
    safePage * RUNS_PAGE_SIZE,
    safePage * RUNS_PAGE_SIZE + RUNS_PAGE_SIZE,
  )
  const selectedRuns = allRuns.filter((run) => selectedRunIds.has(run.run_id))

  useEffect(() => {
    setRunPage(0)
    setSelectedRunIds(new Set())
  }, [runStatusFilter, stageTab, row.process_id])

  useEffect(() => {
    if (!expanded) return
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
    onStageChange?.(next)
  }

  const rerunMutation = useMutation({
    mutationFn: async (runs: BulkProcessRun[]) => {
      const results = []
      for (const run of runs) {
        results.push(await rerunBulkProcessRun(run))
      }
      return results
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-process-runs'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-processes'] })
      setSelectedRunIds(new Set())
      setRerunConfirmOpen(false)
    },
  })

  const assignMutation = useMutation({
    mutationFn: async () => {
      const requestIds = [
        ...new Set(
          selectedRuns
            .map((run) => run.request_id)
            .filter((id): id is string => Boolean(id)),
        ),
      ]
      if (requestIds.length === 0) {
        throw new Error('Selected runs have no request ids to assign')
      }
      const email = assignEmail.trim() || me?.email
      if (!email) throw new Error('Assignee email is required')
      return postDropWorkflowAssign({
        request_ids: requestIds,
        assignee_identity: email,
      })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops'] })
      setAssignOpen(false)
      setSelectedRunIds(new Set())
    },
  })

  const when = row.process_at
    ? new Date(row.process_at).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      })
    : '—'
  const intakeLabel = row.intake_source || 'drop'
  const rowTone = running
    ? 'border-b border-emerald-200/70 bg-emerald-50/30 last:border-b-0'
    : pending
      ? 'border-b border-sky-200/70 bg-sky-50/25 last:border-b-0'
      : needsReview
        ? 'border-b border-amber-200/70 bg-amber-50/25 last:border-b-0'
        : 'border-b border-line bg-paper last:border-b-0'

  function toggleRun(runId: string) {
    setSelectedRunIds((current) => {
      const next = new Set(current)
      if (next.has(runId)) next.delete(runId)
      else next.add(runId)
      return next
    })
  }

  function togglePageSelection() {
    const ids = pagedRuns.map((run) => run.run_id)
    const allSelected = ids.every((id) => selectedRunIds.has(id))
    setSelectedRunIds((current) => {
      const next = new Set(current)
      if (allSelected) ids.forEach((id) => next.delete(id))
      else ids.forEach((id) => next.add(id))
      return next
    })
  }

  return (
    <div className={rowTone}>
      <div className="flex flex-col gap-1.5 px-3 py-2.5">
        <div className="flex w-full items-start gap-2">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            className={
              running
                ? 'flex min-w-0 flex-1 items-start gap-2 border-l-2 border-l-emerald-500 pl-2 text-left'
                : pending
                  ? 'flex min-w-0 flex-1 items-start gap-2 border-l-2 border-l-sky-400 pl-2 text-left'
                  : needsReview
                    ? 'flex min-w-0 flex-1 items-start gap-2 border-l-2 border-l-amber-400 pl-2 text-left'
                    : 'flex min-w-0 flex-1 items-start gap-2 border-l-2 border-l-transparent pl-2 text-left'
            }
          >
            <span
              className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center text-[0.65rem] text-mute"
              aria-hidden="true"
            >
              {expanded ? '▼' : '▶'}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                <p className="truncate text-xs font-medium text-ink">{row.label}</p>
                {running ? <RunningPulse /> : null}
                {pending ? <PendingPulse /> : null}
                {needsReview ? <NeedsReviewChip count={reviewCount} /> : null}
              </div>
              <p className="mt-0.5 truncate text-[0.6rem] text-mute">
                {intakeLabel} · {when}
                {running || pending ? ` · ${currentStage}` : ''}
                {derived.failed > 0 ? ` · ${derived.failed} failed` : ''}
                {!running && !pending ? ` · ${status}` : ''}
              </p>
            </div>
          </button>
          <Tooltip>
            <TooltipTrigger asChild>
              <Link
                to="/requests/needs-attention"
                search={{ bulk: row.process_id }}
                className="taste-btn shrink-0 px-2 py-0.5 text-[0.6rem]"
              >
                Matching results
                {reviewCount != null ? ` · ${reviewCount}` : ''}
              </Link>
            </TooltipTrigger>
            <TooltipContent>Open Inbox filtered to this bulk process</TooltipContent>
          </Tooltip>
        </div>

        <div className="grid w-full grid-cols-2 gap-1.5 pl-7 sm:max-w-lg">
          <div className="rounded-md border border-line/80 bg-paper/90 px-2 py-1.5">
            <p className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">
              Duration
            </p>
            <p className="mt-0.5 text-sm font-medium tabular-nums text-ink">
              {duration ?? '—'}
              {duration && running ? (
                <span className="ml-1 text-[0.6rem] font-normal text-mute">so far</span>
              ) : null}
            </p>
          </div>
          {expanded ? (
            <div className="flex items-center gap-2 rounded-md border border-line/80 bg-paper/90 px-2 py-1.5">
              <MiniRing
                percent={estCompletion}
                tone={errorRate > 10 ? 'amber' : 'emerald'}
              />
              <div className="min-w-0">
                <p className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">
                  Est. completion
                </p>
                <p className="text-sm font-medium tabular-nums text-ink">
                  {estCompletion}%
                  <span className="ml-1 text-[0.6rem] font-normal text-mute">
                    · error {errorRate}%
                  </span>
                </p>
              </div>
            </div>
          ) : (
            <div className="rounded-md border border-line/80 bg-paper/90 px-2 py-1.5">
              <p className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">
                Progress
              </p>
              <p className="mt-0.5 text-sm font-medium tabular-nums text-ink">
                {percent != null ? `${percent}%` : '—'}
                {requestRows != null ? (
                  <span className="ml-1 text-[0.6rem] font-normal text-mute">
                    · {requestRows} req
                  </span>
                ) : null}
              </p>
              <div className="relative mt-1 h-1 overflow-hidden rounded-full bg-panel">
                <div
                  className={
                    running
                      ? 'h-full rounded-full bg-emerald-600 transition-[width]'
                      : pending
                        ? 'h-full rounded-full bg-sky-600 transition-[width]'
                        : 'h-full rounded-full bg-habeas-navy transition-[width]'
                  }
                  style={{ width: `${percent ?? 0}%` }}
                />
              </div>
            </div>
          )}
        </div>

        <div className="w-full pl-7">
          <BulkStageStrip
            detail={detail}
            loading={detailQuery.isPending && !detail}
            duration={duration}
            running={running || pending}
            activeTab={stageTab}
            onSelectTab={selectStage}
          />
        </div>
      </div>

      {expanded ? (
        <div
          className={
            running
              ? 'space-y-2 border-t border-emerald-100/80 bg-emerald-50/15 px-3 py-2.5 pl-10'
              : pending
                ? 'space-y-2 border-t border-sky-100/80 bg-sky-50/15 px-3 py-2.5 pl-10'
                : needsReview
                  ? 'space-y-2 border-t border-amber-100/80 bg-amber-50/15 px-3 py-2.5 pl-10'
                  : 'space-y-2 border-t border-line/60 px-3 py-2.5 pl-10'
          }
        >
          {detailQuery.isError ? (
            <p className="text-[0.65rem] text-red-700">Could not load stage detail</p>
          ) : null}

          {stageTab === 'matching' ? (
            <div className="flex justify-start">
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
            </div>
          ) : null}

          <div className="rounded-md border border-line/80 bg-paper">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-2.5 py-1.5">
              <Micro>{activeStage.label} runs</Micro>
              <div className="flex flex-wrap items-center gap-1">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="taste-btn px-2 py-0.5 text-[0.6rem] disabled:opacity-40"
                      disabled={selectedRuns.length === 0 || rerunMutation.isPending}
                      onClick={() => setRerunConfirmOpen(true)}
                    >
                      Re-run
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>Queue selected runs again via admin-api</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="taste-btn px-2 py-0.5 text-[0.6rem] disabled:opacity-40"
                      disabled={
                        selectedRuns.every((run) => !run.request_id) ||
                        assignMutation.isPending
                      }
                      onClick={() => {
                        setAssignEmail(me?.email ?? '')
                        setAssignOpen(true)
                      }}
                    >
                      Assign
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>
                    Assign selected request ids to a reviewer
                  </TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="taste-btn px-2 py-0.5 text-[0.6rem] disabled:opacity-40"
                      disabled={selectedRuns.length !== 1}
                      onClick={() => setDetailRun(selectedRuns[0] ?? null)}
                    >
                      Details
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>Open a detailed popup for one selected run</TooltipContent>
                </Tooltip>
                <span className="text-[0.65rem] tabular-nums text-mute">
                  {filteredRuns.length}/{allRuns.length}
                </span>
              </div>
            </div>
            <div
              className="flex flex-wrap gap-1 border-b border-line px-2.5 py-1.5"
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
                    <TooltipContent>Show {filter.label.toLowerCase()} runs</TooltipContent>
                  </Tooltip>
                )
              })}
            </div>
            {runsQuery.isError ? (
              <p className="px-2.5 py-2 text-[0.7rem] text-red-700">
                Could not load individual runs.
              </p>
            ) : runsQuery.isPending && !runsQuery.data ? (
              <div className="p-2.5">
                <SkeletonLines lines={3} />
              </div>
            ) : filteredRuns.length === 0 ? (
              <p className="px-2.5 py-2 text-[0.7rem] text-ink-soft">
                {stageTab === 'fulfillment'
                  ? 'No matching-stage runs yet — fulfillment is tracked per request response_status.'
                  : 'No individual runs match this filter.'}
              </p>
            ) : (
              <>
                <div className="max-h-64 overflow-auto">
                  <table className="taste-table">
                    <thead>
                      <tr>
                        <th className="w-8">
                          <input
                            type="checkbox"
                            aria-label="Select page"
                            checked={
                              pagedRuns.length > 0 &&
                              pagedRuns.every((run) => selectedRunIds.has(run.run_id))
                            }
                            onChange={togglePageSelection}
                          />
                        </th>
                        <th>Run</th>
                        <th>Step</th>
                        <th>Status</th>
                        <th>Age</th>
                        <th>Attempt</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pagedRuns.map((run) => (
                        <tr
                          key={run.run_id}
                          className="cursor-pointer hover:bg-panel/60"
                          onClick={() => setDetailRun(run)}
                        >
                          <td onClick={(event) => event.stopPropagation()}>
                            <input
                              type="checkbox"
                              aria-label={`Select ${run.run_id}`}
                              checked={selectedRunIds.has(run.run_id)}
                              onChange={() => toggleRun(run.run_id)}
                            />
                          </td>
                          <td className="max-w-[9rem] truncate font-mono text-xs">
                            {run.run_id}
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
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-2.5 py-1.5">
                  <p className="text-[0.65rem] text-mute">
                    Page {safePage + 1} of {pageCount}
                  </p>
                  <div className="flex gap-1">
                    <button
                      type="button"
                      className="taste-btn px-2 py-0.5 text-[0.6rem] disabled:opacity-40"
                      disabled={safePage <= 0}
                      onClick={() => setRunPage((page) => Math.max(0, page - 1))}
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      className="taste-btn px-2 py-0.5 text-[0.6rem] disabled:opacity-40"
                      disabled={safePage >= pageCount - 1}
                      onClick={() =>
                        setRunPage((page) => Math.min(pageCount - 1, page + 1))
                      }
                    >
                      Next
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      ) : null}

      <ConfirmActionDialog
        open={rerunConfirmOpen}
        onOpenChange={setRerunConfirmOpen}
        title={`Re-run ${selectedRuns.length} run${selectedRuns.length === 1 ? '' : 's'}?`}
        description="Queues the selected attempts again through admin-api. Download re-queues the connector; land/promote target attempt ids when available."
        confirmLabel="Re-run selected"
        confirming={rerunMutation.isPending}
        onConfirm={() => rerunMutation.mutate(selectedRuns)}
      />

      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Assign requests</DialogTitle>
            <DialogDescription>
              Assign request ids from the selected runs to a reviewer identity.
            </DialogDescription>
          </DialogHeader>
          <label className="block space-y-1 text-xs text-ink-soft">
            <span>Assignee email</span>
            <input
              className="w-full rounded-md border border-line bg-paper px-2 py-1.5 font-mono text-xs text-ink"
              value={assignEmail}
              onChange={(event) => setAssignEmail(event.target.value)}
              placeholder="name@example.com"
            />
          </label>
          {assignMutation.isError ? (
            <p className="text-xs text-red-700">
              {assignMutation.error instanceof Error
                ? assignMutation.error.message
                : 'Assign failed'}
            </p>
          ) : null}
          <DialogFooter>
            <button
              type="button"
              className="taste-btn px-3 py-1.5 text-xs"
              onClick={() => setAssignOpen(false)}
              disabled={assignMutation.isPending}
            >
              Cancel
            </button>
            <button
              type="button"
              className="taste-btn-primary px-3 py-1.5 text-xs"
              disabled={assignMutation.isPending}
              onClick={() => assignMutation.mutate()}
            >
              {assignMutation.isPending ? 'Assigning…' : 'Assign'}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={detailRun != null}
        onOpenChange={(open) => {
          if (!open) setDetailRun(null)
        }}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Run detail</DialogTitle>
            <DialogDescription>
              Compact view for this attempt. Open the full Runs page for timeline and output.
            </DialogDescription>
          </DialogHeader>
          {detailRun ? (
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <dt className="text-mute">Run</dt>
                <dd className="font-mono text-ink">{detailRun.run_id}</dd>
              </div>
              <div>
                <dt className="text-mute">Status</dt>
                <dd className="capitalize text-ink">
                  {detailRun.status.replaceAll('_', ' ')}
                </dd>
              </div>
              <div>
                <dt className="text-mute">Step</dt>
                <dd className="font-mono text-ink">{detailRun.step}</dd>
              </div>
              <div>
                <dt className="text-mute">Attempt</dt>
                <dd className="tabular-nums text-ink">{detailRun.attempt_number}</dd>
              </div>
              <div>
                <dt className="text-mute">Age</dt>
                <dd className="tabular-nums text-ink">
                  {detailRun.started_at ? runAgeLabel(detailRun.started_at) : '—'}
                </dd>
              </div>
              <div>
                <dt className="text-mute">Request</dt>
                <dd className="font-mono text-ink">{detailRun.request_id ?? '—'}</dd>
              </div>
            </dl>
          ) : null}
          <DialogFooter>
            {detailRun ? (
              <Link
                to="/ops/runs/$job/$attemptId"
                params={{
                  job: detailRun.job,
                  attemptId: String(detailRun.attempt_id),
                }}
                className="taste-btn-primary px-3 py-1.5 text-xs"
              >
                Full runs page
              </Link>
            ) : null}
            <button
              type="button"
              className="taste-btn px-3 py-1.5 text-xs"
              onClick={() => setDetailRun(null)}
            >
              Close
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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

  const individualRunStatus =
    overallStatus === 'complete'
      ? 'success'
      : overallStatus === 'in_progress'
        ? 'open'
        : overallStatus === 'needs_attention'
          ? 'attention'
          : 'attention'

  return (
    <div className="rounded-md border border-line bg-paper">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Micro>Request Processing Pipeline</Micro>
          {activeCount > 0 ? <RunningPulse label={`${activeCount} running`} /> : null}
          {pendingCount > 0 ? <PendingPulse label={`${pendingCount} pending`} /> : null}
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
              defaultStatus={individualRunStatus}
              embedded
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
          tone="sky"
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
}: {
  disabled?: boolean
  onQueued: (label: string, result: unknown) => void
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
        <DialogContent className="relative max-w-md overflow-hidden">
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
          {runMutation.isError ? (
            <p className="text-xs text-red-700">
              {runMutation.error instanceof Error
                ? runMutation.error.message
                : 'Pipeline queue failed'}
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
              onClick={() => runMutation.mutate()}
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


function ConfigurationsPanel({
  data,
  scheduleNext,
  scheduleLast,
  scheduleUtc,
  scheduleCadence,
}: {
  data: DropPipelineStatus | undefined
  scheduleNext: string | null
  scheduleLast: string | null
  scheduleUtc: string | null
  scheduleCadence: string | null
}) {
  const workersQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-workers', 'config'],
    queryFn: getDropWorkers,
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })
  const workers = workersQuery.data?.workers ?? []
  const cadenceLabel = scheduleCadence
    ? scheduleCadence.replaceAll('_', ' ')
    : null

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-line bg-paper p-4">
        <Micro>Scheduled workers</Micro>
        <p className="mt-1 max-w-2xl text-xs text-ink-soft">
          CA DROP retrieval fires on the connector schedule (interval gate). Other workers claim
          from attempt queues — concurrency and retry floors below. Edit schedules under Workers
          → Settings.
        </p>
        <p className="mt-2 text-xs">
          <Link to="/ops/workers/settings" className="taste-link">
            Edit schedules
          </Link>
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div className="rounded-md border border-line/80 px-3 py-2">
            <p className="text-[0.65rem] uppercase tracking-wide text-mute">Next CA DROP</p>
            <p className="mt-1 text-sm tabular-nums text-ink">
              {scheduleNext ? new Date(scheduleNext).toLocaleString() : '—'}
            </p>
            <p className="mt-0.5 text-[0.65rem] text-mute">
              {scheduleUtc
                ? `${cadenceLabel ?? 'schedule'} · tick ${scheduleUtc} UTC`
                : 'Schedule unset'}
            </p>
          </div>
          <div className="rounded-md border border-line/80 px-3 py-2">
            <p className="text-[0.65rem] uppercase tracking-wide text-mute">Last success</p>
            <p className="mt-1 text-sm tabular-nums text-ink">
              {scheduleLast ? new Date(scheduleLast).toLocaleString() : '—'}
            </p>
          </div>
          <div className="rounded-md border border-line/80 px-3 py-2">
            <p className="text-[0.65rem] uppercase tracking-wide text-mute">Workers up</p>
            <p className="mt-1 text-sm tabular-nums text-ink">
              {data
                ? `${WORKER_ORDER.filter((name) => data.worker_health[name]?.ok).length}/${WORKER_ORDER.length}`
                : '—'}
            </p>
          </div>
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="taste-table">
            <thead>
              <tr>
                <th>Worker</th>
                <th>Ready</th>
                <th>Pending</th>
                <th>In flight</th>
                <th>Concurrency</th>
                <th>Max attempts</th>
              </tr>
            </thead>
            <tbody>
              {workers.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-mute">
                    {workersQuery.isPending ? 'Loading workers…' : 'No worker records.'}
                  </td>
                </tr>
              ) : (
                workers.map((worker) => (
                  <tr key={worker.name}>
                    <td className="font-mono text-xs">
                      <Link
                        to="/ops/runs"
                        search={runsSearchForWorker(worker.name)}
                        className="text-habeas-mid underline decoration-habeas-mid/30 underline-offset-2"
                      >
                        {worker.name}
                      </Link>
                    </td>
                    <td className={worker.ok ? 'text-emerald-700' : 'text-red-700'}>
                      {worker.ok ? 'up' : 'down'}
                    </td>
                    <td className="tabular-nums">{worker.queue.pending}</td>
                    <td className="tabular-nums">{worker.queue.in_flight}</td>
                    <td className="tabular-nums">
                      {worker.pool.configured_concurrency ?? '—'}
                    </td>
                    <td className="tabular-nums">{worker.pool.max_attempts ?? '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <RetryConfigPanel />

      <div className="rounded-md border border-line bg-paper p-4">
        <Micro>Auto-process steps & rules</Micro>
        <p className="mt-1 max-w-2xl text-xs text-ink-soft">
          Use <span className="font-medium text-ink">Run Pipeline</span> for CA DROP
          (download → land → promote). Expand a bulk card for stage detail. Matching review and
          fulfill / decline live in Inbox. Hash refresh enqueues and processes in one action.
        </p>
        <ul className="mt-3 space-y-1.5 text-xs text-ink-soft">
          <li>
            <span className="font-medium text-ink">CA DROP</span> — scheduled connector or Run
            Pipeline.
          </li>
          <li>
            <span className="font-medium text-ink">Ingest</span> — Land + Promote (combined on bulk
            cards).
          </li>
          <li>
            <span className="font-medium text-ink">Matching</span> — workers claim on schedule;
            review in Inbox.
          </li>
          <li>
            <span className="font-medium text-ink">Hash refresh</span> — enqueue then process from
            the Hash refresh tab.
          </li>
        </ul>
        <p className="mt-3 text-xs text-ink-soft">
          <Link to="/ops/workers/settings" className="text-habeas-mid underline-offset-2 hover:underline">
            Workers → Settings
          </Link>
          {' · '}
          <Link
            to="/"
            search={{ tab: 'hash_refresh' }}
            className="text-habeas-mid underline-offset-2 hover:underline"
          >
            Hash refresh tab
          </Link>
        </p>
      </div>
    </div>
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
  hashIndexMutation,
  actionMutation,
}: {
  data: DropPipelineStatus | undefined
  showSkeleton: boolean
  hashState: string
  setHashState: (state: string) => void
  hashPending: boolean
  hashWorkerDown: boolean
  lastRun: HashIndexRefreshStatus['last_run']
  hashIndexMutation: {
    isPending: boolean
    mutate: (action: { kind: 'refresh-state'; state: string } | { kind: 'refresh-all' }) => void
  }
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
                hashIndexMutation.isPending ||
                actionMutation.isPending
              }
              onClick={() =>
                hashIndexMutation.mutate({ kind: 'refresh-state', state: hashState })
              }
            >
              Refresh state
            </button>
            <button
              type="button"
              className="taste-btn px-3 py-1.5 text-xs"
              disabled={
                showSkeleton ||
                hashPending ||
                hashIndexMutation.isPending ||
                actionMutation.isPending
              }
              onClick={() => hashIndexMutation.mutate({ kind: 'refresh-all' })}
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
    onSuccess: ({ data }) => {
      setActionResult(JSON.stringify(data, null, 2))
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-processes'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'approvals'] })
    },
    onError: (error) => {
      setActionResult(error instanceof Error ? error.message : String(error))
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
          <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">Ops</p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight text-ink">Dashboard</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {pipelineQuery.isFetching && !pipelineQuery.isPending ? (
            <span className="rounded-md border border-line px-2 py-0.5 text-[0.65rem] text-mute">
              Refreshing
            </span>
          ) : null}
          <RunPipelineButton
            disabled={showSkeleton}
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
        <div ref={actionResultRef}>
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

      {tab === 'hash_refresh' && (
        <HashIndexPanel
          data={data}
          showSkeleton={showSkeleton}
          hashState={hashState}
          setHashState={setHashState}
          hashPending={hashPending}
          hashWorkerDown={hashWorkerDown}
          lastRun={lastRun ?? null}
          hashIndexMutation={hashIndexMutation}
          actionMutation={actionMutation}
        />
      )}

      {tab === 'configurations' && (
        <ConfigurationsPanel
          data={data}
          scheduleNext={caSchedule?.next_run_at ?? null}
          scheduleLast={caSchedule?.last_success_at ?? null}
          scheduleUtc={caSchedule?.schedule_utc ?? null}
          scheduleCadence={caSchedule?.cadence ?? null}
        />
      )}

      {tab === 'hash_refresh' && lastAction && actionResult ? (
        <div ref={actionResultRef}>
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
