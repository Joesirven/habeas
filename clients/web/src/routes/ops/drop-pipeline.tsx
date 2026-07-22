import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useBlocker, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { SkeletonLines } from '@/components/AppShell'
import { ConfirmActionDialog } from '@/components/ui/dialog'
import { RoleGate, isSuperAdmin } from '@/lib/auth'
import {
  getDropBulkProcess,
  getDropMatchingResultDetail,
  getDropMatchingResults,
  getDropPipeline,
  getDropWorkers,
  listDropBulkProcesses,
  listDropBulkProcessRuns,
  listRuns,
  postDropDispatch,
  postDropDownload,
  postDropFulfill,
  postDropLand,
  postDropMatch,
  postDropMatchingResultDecline,
  postDropMatchingResultPromote,
  postDropMatchingResultsBulkApprove,
  postDropMatchingResultsBulkDecline,
  postDropPromote,
  postDropWorkflowAssign,
  postDropWorkflowAssignByMatchType,
  postHashIndexRefreshEnqueue,
  postHashIndexRefreshEnqueueAll,
  postHashIndexRefreshProcess,
  type BulkProcessDetail,
  type BulkProcessRunGroup,
  type BulkProcessStageCounts,
  type BulkProcessSummary,
  type DropPipelineStatus,
  type HashIndexRefreshStatus,
  type MatchTypeFilter,
  type MatchingAttemptRow,
  type MatchingResultDetail,
  type MatchingResultsStats,
  type StepStatusCount,
  type WorkerHealthProbe,
} from '@/lib/api'
import { RetryConfigPanel } from '@/routes/ops/health/configuration'

type PipelineTab =
  | 'home'
  | 'download'
  | 'ingest'
  | 'matching'
  | 'fulfillment'
  | 'hash_refresh'
  | 'history'
  | 'configurations'

function approachingSlaFrom(data: DropPipelineStatus | undefined) {
  return data?.approaching_sla
}

function matchTypeFromCount(matchCount: number): MatchTypeFilter {
  if (matchCount <= 0) return 'not_found'
  if (matchCount === 1) return 'single_match'
  return 'multi_match'
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
  { key: 'home', label: 'Home' },
  { key: 'download', label: 'Download' },
  { key: 'ingest', label: 'Ingest' },
  { key: 'matching', label: 'Matching' },
  { key: 'fulfillment', label: 'Fulfillment' },
  { key: 'hash_refresh', label: 'Hash refresh' },
  { key: 'history', label: 'History' },
  { key: 'configurations', label: 'Configurations' },
]

const TAB_HISTORY_STAGES: Partial<Record<PipelineTab, string>> = {
  download: 'download',
  ingest: 'land,promote',
  matching: 'matching',
}

const TAB_BULK_STAGES: Partial<
  Record<PipelineTab, { key: keyof BulkProcessDetail['stages']; label: string }[]>
> = {
  home: [
    { key: 'download', label: 'Download' },
    { key: 'land', label: 'Land' },
    { key: 'promote', label: 'Promote' },
    { key: 'matching', label: 'Matching' },
    { key: 'review', label: 'Review' },
    { key: 'fulfillment', label: 'Fulfill' },
  ],
  download: [{ key: 'download', label: 'Download' }],
  ingest: [
    { key: 'land', label: 'Land' },
    { key: 'promote', label: 'Promote' },
  ],
  matching: [
    { key: 'matching', label: 'Matching' },
    { key: 'review', label: 'Review' },
  ],
  fulfillment: [{ key: 'fulfillment', label: 'Fulfillment' }],
}

function stageCountsBlurb(stage: BulkProcessStageCounts | undefined): string {
  if (!stage) return '—'
  return `${stage.success}/${stage.total} ok · ${stage.open} open · ${stage.failed} failed`
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
  { key: 'dispatch', label: 'Dispatch matching', run: () => postDropDispatch() },
  { key: 'match', label: 'Run matching', run: () => postDropMatch() },
  { key: 'fulfill', label: 'Fulfill', run: () => postDropFulfill() },
] as const

type ActionKey = (typeof ACTIONS)[number]['key']

const MATCH_TYPE_LABELS: Record<MatchTypeFilter, string> = {
  single_match: 'Single match',
  multi_match: 'Multi-match (status 4)',
  not_found: 'Not found',
}

const MATCH_TYPE_OPTIONS: MatchTypeFilter[] = ['single_match', 'multi_match', 'not_found']

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function summarizeActionPayload(raw: string | null): { status: string | null; blurb: string } {
  if (!raw) return { status: null, blurb: '' }
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
    if (typeof parsed.request_id === 'string') parts.push(`request ${parsed.request_id.slice(0, 8)}…`)
    if (typeof parsed.match_count === 'number') parts.push(`${parsed.match_count} matches`)
    if (typeof parsed.gcs_uri === 'string') {
      const leaf = parsed.gcs_uri.split('/').pop() ?? parsed.gcs_uri
      parts.push(leaf)
    }
    return { status, blurb: parts.join(' · ') || 'Payload ready' }
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
  const { status, blurb } = summarizeActionPayload(actionResult)
  const isError =
    status === 'error' ||
    (actionResult != null &&
      !actionResult.trimStart().startsWith('{') &&
      /error|fail|502|503|401|403/i.test(actionResult))

  if (!lastAction && !actionResult) return null

  return (
    <>
      <div className="min-w-0 rounded-[0.9rem] border border-line bg-paper-raised/80">
        <div className="flex items-start justify-between gap-3 border-b border-line px-3 py-2.5">
          <div className="min-w-0">
            <Micro>Last response</Micro>
            <p className="mt-1 truncate text-sm text-ink">{lastAction ?? 'Action'}</p>
            <p className="mt-0.5 truncate text-xs text-ink-soft">
              {status ? (
                <span className={isError ? 'text-red-700' : 'text-emerald-700'}>{status}</span>
              ) : null}
              {status && blurb ? <span className="text-mute"> · </span> : null}
              {blurb || '—'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <button
              type="button"
              className="taste-btn px-2.5 py-1 text-[0.65rem]"
              onClick={() => setExpanded(true)}
            >
              View payload
            </button>
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
        <pre className="max-h-28 overflow-auto overscroll-contain px-3 py-2 font-mono text-[0.7rem] leading-relaxed text-ink-soft [overflow-wrap:anywhere] whitespace-pre-wrap break-all">
          {actionResult ?? ''}
        </pre>
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
      aria-label="DROP pipeline stages"
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

function ActionButtons({
  keys,
  showSkeleton,
  postMatchOpen,
  actionMutation,
}: {
  keys: ActionKey[]
  showSkeleton: boolean
  postMatchOpen: boolean
  actionMutation: {
    isPending: boolean
    variables?: ActionKey
    mutate: (key: ActionKey) => void
  }
}) {
  const filtered = ACTIONS.filter((action) => keys.includes(action.key))
  return (
    <div className="flex flex-wrap gap-1.5">
      {filtered.map((action, index) => {
        const busy = actionMutation.isPending && actionMutation.variables === action.key
        return (
          <button
            key={action.key}
            type="button"
            className={
              index === 0
                ? 'taste-btn-primary px-3 py-1.5 text-xs'
                : 'taste-btn px-3 py-1.5 text-xs'
            }
            disabled={actionMutation.isPending || showSkeleton || postMatchOpen}
            onClick={() => actionMutation.mutate(action.key)}
          >
            <span className="inline-flex items-center gap-2">
              {action.label}
              {busy ? (
                <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              ) : (
                <span className="font-mono text-[0.6rem] opacity-50">
                  {String(index + 1).padStart(2, '0')}
                </span>
              )}
            </span>
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

function ProcessRunsHistoryPanel({
  stage,
  processId,
  days = 1,
  emptyLabel,
}: {
  stage: string
  processId?: number
  days?: number
  emptyLabel: string
}) {
  const [statusFilter, setStatusFilter] = useState<string>('')
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
    queryFn: () =>
      listDropBulkProcessRuns({
        stage,
        days,
        process_id: processId,
        status: statusFilter || undefined,
      }),
    refetchInterval: 5_000,
    placeholderData: (previous) => previous,
  })

  const groups = runsQuery.data?.groups ?? []
  const totalRuns = groups.reduce((sum, group) => sum + group.run_count, 0)

  return (
    <div className="rounded-md border border-line bg-paper">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <Micro>Runs by bulk process</Micro>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="rounded-md border border-line bg-paper px-2 py-1 text-[0.65rem] text-ink"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            aria-label="Filter run status"
          >
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="success">Success</option>
            <option value="failed">Failed</option>
          </select>
          <span className="text-[0.65rem] tabular-nums text-mute">
            {groups.length} processes · {totalRuns} runs
          </span>
        </div>
      </div>
      {runsQuery.isError ? (
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
      )}
    </div>
  )
}

function BatchRequestRunsList({
  onSelectProcess,
  selectedProcessId,
}: {
  onSelectProcess: (id: number) => void
  selectedProcessId?: number
}) {
  const [days, setDays] = useState(7)
  const [intake, setIntake] = useState('drop')
  const [downloadStatus, setDownloadStatus] = useState('')
  const [overallStatus, setOverallStatus] = useState('')

  const listQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'drop-processes',
      'home-list',
      days,
      intake,
      downloadStatus,
      overallStatus,
    ],
    queryFn: () =>
      listDropBulkProcesses({
        days,
        intake_source: intake || undefined,
        download_status: downloadStatus || undefined,
        overall_status: overallStatus || undefined,
        include_summary: true,
        limit: 50,
      }),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const rows = listQuery.data?.processes ?? []

  return (
    <div className="rounded-md border border-line bg-paper">
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-line px-3 py-2.5">
        <div>
          <Micro>Batch request runs</Micro>
          <p className="mt-0.5 text-[0.65rem] text-ink-soft">
            Bulk processes keyed by intake payload + datetime
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <select
            className="rounded-md border border-line bg-paper px-2 py-1 text-[0.65rem]"
            value={intake}
            onChange={(event) => setIntake(event.target.value)}
            aria-label="Filter intake"
          >
            <option value="drop">drop</option>
          </select>
          <select
            className="rounded-md border border-line bg-paper px-2 py-1 text-[0.65rem]"
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
            aria-label="Filter time window"
          >
            <option value={1}>1 day</option>
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
          </select>
          <select
            className="rounded-md border border-line bg-paper px-2 py-1 text-[0.65rem]"
            value={downloadStatus}
            onChange={(event) => setDownloadStatus(event.target.value)}
            aria-label="Filter download status"
          >
            <option value="">Download: any</option>
            <option value="pending">pending</option>
            <option value="in_flight">in_flight</option>
            <option value="success">success</option>
            <option value="submit_error">submit_error</option>
            <option value="outcome_error">outcome_error</option>
          </select>
          <select
            className="rounded-md border border-line bg-paper px-2 py-1 text-[0.65rem]"
            value={overallStatus}
            onChange={(event) => setOverallStatus(event.target.value)}
            aria-label="Filter overall status"
          >
            <option value="">Overall: any</option>
            <option value="in_progress">in_progress</option>
            <option value="complete">complete</option>
            <option value="needs_attention">needs_attention</option>
          </select>
        </div>
      </div>
      {listQuery.isError ? (
        <p className="px-3 py-3 text-xs text-red-700">Could not load batch runs.</p>
      ) : listQuery.isPending && !listQuery.data ? (
        <div className="p-3">
          <SkeletonLines lines={4} />
        </div>
      ) : rows.length === 0 ? (
        <p className="px-3 py-3 text-xs text-ink-soft">No bulk processes in this window.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="taste-table">
            <thead>
              <tr>
                <th>Process</th>
                <th>Intake</th>
                <th>Download</th>
                <th>Overall</th>
                <th>Progress</th>
                <th>Requests</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row: BulkProcessSummary) => {
                const selected = selectedProcessId === row.process_id
                return (
                  <tr
                    key={row.process_id}
                    className={selected ? 'bg-habeas-navy/5' : undefined}
                  >
                    <td className="text-xs">{row.label}</td>
                    <td className="font-mono text-xs">{row.intake_source}</td>
                    <td className="text-xs">{row.download_status.replaceAll('_', ' ')}</td>
                    <td className="text-xs">
                      {row.overall?.status?.replaceAll('_', ' ') ?? '—'}
                    </td>
                    <td className="tabular-nums text-xs">
                      {row.overall?.percent != null ? `${row.overall.percent}%` : '—'}
                    </td>
                    <td className="tabular-nums text-xs">{row.request_rows ?? '—'}</td>
                    <td>
                      <button
                        type="button"
                        className="taste-btn px-2 py-0.5 text-[0.65rem]"
                        onClick={() => onSelectProcess(row.process_id)}
                      >
                        {selected ? 'Selected' : 'Track'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function CompactOpsMetrics({
  approachingDeadlineTotal,
  approachingReview,
  spineCount,
  nextCaDrop,
  scheduleBlurb,
  reviewPending,
  matchingQueue,
  workersUp,
  workersTotal,
}: {
  approachingDeadlineTotal: number | null
  approachingReview: number | null
  spineCount: number | string
  nextCaDrop: string
  scheduleBlurb: string
  reviewPending: number | string
  matchingQueue: number | string
  workersUp: number | null
  workersTotal: number
}) {
  const cells = [
    {
      label: 'Approaching',
      value: approachingDeadlineTotal ?? '—',
      hint: `review ${approachingReview ?? '—'}`,
      href: '/requests/needs-attention' as const,
    },
    {
      label: 'Spine',
      value: spineCount,
      hint: 'thin DROP',
    },
    {
      label: 'Next CA DROP',
      value: nextCaDrop,
      hint: scheduleBlurb,
      wide: true,
    },
    {
      label: 'Review',
      value: reviewPending,
      hint: 'gates',
    },
    {
      label: 'Match Q',
      value: matchingQueue,
      hint: 'pending',
    },
    {
      label: 'Workers',
      value: workersUp != null ? `${workersUp}/${workersTotal}` : '—',
      hint: 'up',
      href: '/ops/workers' as const,
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-6">
      {cells.map((cell) => (
        <div
          key={cell.label}
          className={`rounded border border-line bg-paper px-2 py-1.5 ${
            cell.wide ? 'sm:col-span-1' : ''
          }`}
        >
          <p className="text-[0.6rem] font-medium uppercase tracking-wide text-mute">
            {cell.label}
          </p>
          <p
            className={`mt-0.5 font-semibold tabular-nums leading-tight text-ink ${
              cell.wide ? 'truncate text-xs' : 'text-base'
            }`}
            title={typeof cell.value === 'string' ? cell.value : undefined}
          >
            {cell.value}
          </p>
          <p className="truncate text-[0.6rem] text-ink-soft">
            {cell.hint}
            {cell.href ? (
              <>
                {' · '}
                <Link
                  to={cell.href}
                  className="text-habeas-navy underline-offset-2 hover:underline"
                >
                  open
                </Link>
              </>
            ) : null}
          </p>
        </div>
      ))}
    </div>
  )
}

function BulkProcessTracker({
  processId,
  onSelectProcess,
  detail,
  processes,
  loading,
}: {
  processId: number | undefined
  onSelectProcess: (id: number | undefined) => void
  detail: BulkProcessDetail | undefined
  processes: { process_id: number; label: string; download_status: string }[]
  loading: boolean
}) {
  const stages = TAB_BULK_STAGES.home ?? []
  const percent = detail?.overall.percent ?? 0
  const status = detail?.overall.status ?? '—'

  return (
    <div className="rounded-md border border-line bg-paper p-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <Micro>Latest bulk process</Micro>
          <p className="mt-0.5 text-sm font-medium text-ink">
            {detail?.label ?? (loading ? 'Loading…' : 'No recent bulk process')}
          </p>
          <p className="mt-0.5 text-[0.65rem] text-ink-soft">
            {detail
              ? `${detail.request_rows} spine · ${detail.raw_rows} raw · ${status.replaceAll('_', ' ')}`
              : processes.length === 0
                ? 'No download attempts in the last 30 days'
                : 'Select a process'}
          </p>
        </div>
        <label className="flex items-center gap-1.5 text-xs text-ink-soft">
          <span className="taste-micro">Recent</span>
          <select
            className="min-w-[14rem] rounded-md border border-line bg-paper px-2 py-1 text-xs text-ink"
            value={processId ?? ''}
            onChange={(event) => {
              const value = event.target.value
              onSelectProcess(value ? Number.parseInt(value, 10) : undefined)
            }}
            aria-label="Recent bulk process"
          >
            <option value="">Select process…</option>
            {processes.map((process) => (
              <option key={process.process_id} value={process.process_id}>
                {process.label} · {process.download_status}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-2">
        <div className="mb-1 flex items-center justify-between text-[0.65rem] text-mute">
          <span>Batch progress</span>
          <span className="tabular-nums text-ink">{percent}%</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-panel">
          <div
            className="h-full rounded-full bg-habeas-navy transition-[width]"
            style={{ width: `${percent}%` }}
          />
        </div>
      </div>

      <div className="mt-2 grid gap-1.5 sm:grid-cols-3 lg:grid-cols-6">
        {stages.map((stage) => {
          const counts = detail?.stages[stage.key]
          const active = detail?.overall.current_stage === stage.key
          return (
            <div
              key={stage.key}
              className={`rounded border px-2 py-1 ${
                active ? 'border-habeas-navy/40 bg-habeas-navy/5' : 'border-line/80'
              }`}
            >
              <p className="text-[0.6rem] uppercase tracking-wide text-mute">{stage.label}</p>
              <p className="text-[0.7rem] tabular-nums text-ink">
                {counts ? `${counts.success}/${counts.total}` : '—'}
                <span className="ml-1 text-[0.6rem] text-ink-soft">
                  {counts ? `${counts.open} open` : ''}
                </span>
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function BulkStepSummary({
  tab,
  detail,
}: {
  tab: PipelineTab
  detail: BulkProcessDetail | undefined
}) {
  const stageKeys = TAB_BULK_STAGES[tab]
  if (
    !stageKeys ||
    tab === 'home' ||
    tab === 'hash_refresh' ||
    tab === 'history' ||
    tab === 'configurations'
  ) {
    return null
  }
  if (!detail) {
    return (
      <div className="rounded-md border border-dashed border-line px-3 py-2 text-xs text-ink-soft">
        Select a bulk process above to see this step’s run summary.
      </div>
    )
  }

  return (
    <div className="rounded-md border border-line bg-paper px-3 py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Micro>Step run summary · {detail.label}</Micro>
        <span className="text-[0.65rem] text-mute">
          Current stage {detail.overall.current_stage.replaceAll('_', ' ')}
        </span>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {stageKeys.map((stage) => {
          const counts = detail.stages[stage.key]
          return (
            <div key={stage.key} className="rounded-md border border-line/70 px-2.5 py-2">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                {stage.label}
              </p>
              <p className="mt-1 text-xs tabular-nums text-ink">{stageCountsBlurb(counts)}</p>
              {counts?.by_list_type && counts.by_list_type.length > 0 ? (
                <p className="mt-1 text-[0.65rem] text-ink-soft">
                  {counts.by_list_type
                    .slice(0, 4)
                    .map(
                      (row) =>
                        `${row.list_type ?? '—'} ${row.status}×${row.count}`,
                    )
                    .join(' · ')}
                </p>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
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
                        to="/ops/workers/$workerName"
                        params={{ workerName: worker.name }}
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
          Stage actions stay operator-triggered from the Dashboard tabs. Hash refresh requires
          enqueue then Process. Matching opens a required review gate after a successful run.
          Fulfillment only processes DROP rows with an approved matching.review gate.
        </p>
        <ul className="mt-3 space-y-1.5 text-xs text-ink-soft">
          <li>
            <span className="font-medium text-ink">Download</span> — scheduled connector retrieval
            (above) or manual Download ZIP.
          </li>
          <li>
            <span className="font-medium text-ink">Ingest</span> — Land then Promote; open attempts
            claim when the ingestor is up.
          </li>
          <li>
            <span className="font-medium text-ink">Matching</span> — Dispatch then Run; post-match
            dialog forces review or bulk approve.
          </li>
          <li>
            <span className="font-medium text-ink">Hash refresh</span> — per-state or all-states
            enqueue; Process drains the queue (see Hash refresh tab).
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

function CountTable({ rows, empty }: { rows: StepStatusCount[]; empty: string }) {
  if (rows.length === 0) {
    return <p className="text-sm text-ink-soft">{empty}</p>
  }
  return (
    <table className="taste-table">
      <thead>
        <tr>
          <th className="!px-0">Step</th>
          <th className="!px-0">Status</th>
          <th className="!px-0">Count</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.step}-${row.status}`}>
            <td className="!px-0 font-mono text-xs">{row.step}</td>
            <td className="!px-0">{row.status}</td>
            <td className="!px-0 tabular-nums">{row.count}</td>
          </tr>
        ))}
      </tbody>
    </table>
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

const INGEST_OPEN_STATUSES = new Set(['pending', 'claimed', 'in_flight'])
const INGEST_FAILED_STATUSES = new Set([
  'submit_error',
  'outcome_error',
  'timeout',
  'abandoned',
])

function summarizeIngestStep(rows: StepStatusCount[], step: string) {
  const filtered = rows.filter((row) => row.step === step)
  let open = 0
  let failed = 0
  let success = 0
  for (const row of filtered) {
    if (INGEST_OPEN_STATUSES.has(row.status)) open += row.count
    else if (INGEST_FAILED_STATUSES.has(row.status)) failed += row.count
    else if (row.status === 'success') success += row.count
  }
  return {
    rows: filtered.map((row) => ({ status: row.status, count: row.count })),
    open,
    failed,
    success,
  }
}

const RESPONSE_STATUS_LABELS: Record<number, string> = {
  2: 'Exempted',
  3: 'Deleted',
  4: 'Opted out',
  5: 'Not found',
}

function responseStatusLabel(value: number | null): string {
  if (value == null) return 'unset (null)'
  return RESPONSE_STATUS_LABELS[value] ?? String(value)
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

function WorkerHealthRow({ probe }: { probe: WorkerHealthProbe }) {
  return (
    <tr>
      <td className="font-mono text-xs">{probe.name}</td>
      <td>
        <span className={probe.ok ? 'text-emerald-700' : 'text-red-700'}>
          {probe.ok ? 'up' : 'down'}
        </span>
      </td>
      <td className="tabular-nums text-ink-soft">{probe.status_code ?? '—'}</td>
      <td className="font-mono text-xs text-mute">{probe.ready?.status ?? '—'}</td>
    </tr>
  )
}

function StatsStrip({ stats }: { stats: MatchingResultsStats }) {
  return (
    <div className="flex flex-wrap gap-2">
      <span className="glass px-2.5 py-1 text-xs text-ink-soft">
        Total <span className="tabular-nums text-ink">{stats.total}</span>
      </span>
      <span className="glass px-2.5 py-1 text-xs text-ink-soft">
        Single <span className="tabular-nums text-ink">{stats.single_match}</span>
      </span>
      <span className="glass px-2.5 py-1 text-xs text-ink-soft">
        Multi (4) <span className="tabular-nums text-ink">{stats.multi_match}</span>
      </span>
      <span className="glass px-2.5 py-1 text-xs text-ink-soft">
        Not found <span className="tabular-nums text-ink">{stats.not_found}</span>
      </span>
      <span className="glass px-2.5 py-1 text-xs text-ink-soft">
        Review pending <span className="tabular-nums text-ink">{stats.review_pending}</span>
      </span>
    </div>
  )
}

type PostMatchChoice = 'review_results' | 'bulk_approve'

function PostMatchDialog({
  open,
  matchSummary,
  onChoose,
}: {
  open: boolean
  matchSummary: string | null
  onChoose: (choice: PostMatchChoice) => void
}) {
  const titleId = useId()
  const firstButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (open) firstButtonRef.current?.focus()
  }, [open])

  if (!open) return null

  // Portal above AppShell sticky header (header z-20 + backdrop-filter stacking context).
  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-habeas-navy/45 p-4 backdrop-blur-sm"
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="taste-panel w-full max-w-md p-6 sm:p-7"
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault()
            event.stopPropagation()
          }
        }}
      >
        <Micro>Matching complete</Micro>
        <h3 id={titleId} className="mt-3 font-display text-2xl font-medium tracking-tight text-ink">
          Choose next action
        </h3>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          A matching job finished. Select how to continue — this dialog stays until you choose.
          Navigation is blocked until you pick an action.
        </p>
        {matchSummary && (
          <pre className="mt-4 max-h-36 overflow-auto overscroll-contain rounded-lg border border-line bg-paper-raised p-3 text-xs text-ink-soft [overflow-wrap:anywhere] whitespace-pre-wrap break-all">
            {matchSummary}
          </pre>
        )}
        <div className="mt-6 flex flex-col gap-2">
          <button
            ref={firstButtonRef}
            type="button"
            className="taste-btn-primary w-full justify-between text-left"
            onClick={() => onChoose('review_results')}
          >
            Review matching results
          </button>
          <button
            type="button"
            className="taste-btn w-full justify-between text-left"
            onClick={() => onChoose('bulk_approve')}
          >
            Bulk approve by match type
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function AttemptHistory({ attempts }: { attempts: MatchingAttemptRow[] }) {
  const [openId, setOpenId] = useState<number | null>(null)
  if (attempts.length === 0) {
    return <p className="text-sm text-ink-soft">No matching attempts recorded for this request.</p>
  }
  return (
    <div className="space-y-2">
      <Micro>Attempt history</Micro>
      <ul className="divide-y divide-line rounded-lg border border-line">
        {attempts.map((attempt) => {
          const open = openId === attempt.id
          return (
            <li key={attempt.id} className="px-3 py-2">
              <button
                type="button"
                className="flex w-full items-center justify-between gap-3 text-left text-sm"
                onClick={() => setOpenId(open ? null : attempt.id)}
              >
                <span>
                  #{attempt.attempt_number}{' '}
                  <span className="text-ink-soft">{attempt.status}</span>
                </span>
                <span className="tabular-nums text-xs text-ink-soft">
                  {attempt.completed_at
                    ? new Date(attempt.completed_at).toLocaleString()
                    : attempt.attempted_at
                      ? new Date(attempt.attempted_at).toLocaleString()
                      : '—'}
                </span>
              </button>
              {open && (
                <dl className="mt-2 grid gap-2 rounded-md bg-paper-raised/60 p-3 text-xs sm:grid-cols-2">
                  <div>
                    <dt className="taste-micro">Attempt id</dt>
                    <dd className="mt-0.5 tabular-nums">{attempt.id}</dd>
                  </div>
                  <div>
                    <dt className="taste-micro">Error code</dt>
                    <dd className="mt-0.5 font-mono">{attempt.error_code ?? '—'}</dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="taste-micro">Audit payload (allowlisted)</dt>
                    <dd className="mt-1 overflow-x-auto font-mono text-[11px] text-ink-soft">
                      <pre className="whitespace-pre-wrap">
                        {JSON.stringify(attempt.audit_payload ?? {}, null, 2)}
                      </pre>
                    </dd>
                  </div>
                </dl>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function MatchingResultsPanel({
  focusBulk,
  highlightRequestId,
  preferredBulkType,
}: {
  focusBulk: boolean
  highlightRequestId: string | null
  preferredBulkType: MatchTypeFilter | null
}) {
  const queryClient = useQueryClient()
  const [view, setView] = useState<'list' | 'detail'>('list')
  const [selectedId, setSelectedId] = useState<string | null>(highlightRequestId)
  const [listFilter, setListFilter] = useState<MatchTypeFilter | 'all'>('all')
  const [requestIdQuery, setRequestIdQuery] = useState('')
  const [stateFilter, setStateFilter] = useState<string>('all')
  const [recordedAfter, setRecordedAfter] = useState('')
  const [recordedBefore, setRecordedBefore] = useState('')
  const [bulkType, setBulkType] = useState<MatchTypeFilter>('multi_match')
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set())
  const [assigneeEmail, setAssigneeEmail] = useState('')
  const [confirmBatchAssign, setConfirmBatchAssign] = useState(false)
  const bulkSectionRef = useRef<HTMLDivElement>(null)

  function invalidateMatching() {
    void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-matching-results'] })
    void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
    void queryClient.invalidateQueries({ queryKey: ['admin-api', 'approvals'] })
    if (selectedId) {
      void queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'drop-matching-result', selectedId],
      })
    }
  }

  const trimmedRequestId = requestIdQuery.trim()
  const resultsQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'drop-matching-results',
      listFilter,
      trimmedRequestId,
      stateFilter,
      recordedAfter,
      recordedBefore,
    ],
    queryFn: () =>
      getDropMatchingResults({
        match_type: listFilter === 'all' ? undefined : listFilter,
        q: trimmedRequestId || undefined,
        state: stateFilter === 'all' ? undefined : stateFilter,
        recorded_after: recordedAfter || undefined,
        recorded_before: recordedBefore || undefined,
        limit: 100,
      }),
    refetchInterval: 10_000,
  })

  const detailQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-matching-result', selectedId],
    queryFn: () => getDropMatchingResultDetail(selectedId!),
    enabled: view === 'detail' && Boolean(selectedId),
  })

  const bulkPromoteMutation = useMutation({
    mutationFn: (matchType: MatchTypeFilter) =>
      postDropMatchingResultsBulkApprove({
        match_type: matchType,
        decision_reason: `bulk promote match_type=${matchType}`,
      }),
    onSuccess: () => invalidateMatching(),
  })

  const bulkDeclineMutation = useMutation({
    mutationFn: (matchType: MatchTypeFilter) =>
      postDropMatchingResultsBulkDecline({
        match_type: matchType,
        decision_reason: `bulk decline match_type=${matchType}`,
      }),
    onSuccess: () => invalidateMatching(),
  })

  const promoteMutation = useMutation({
    mutationFn: (requestId: string) =>
      postDropMatchingResultPromote(requestId, {
        decision_reason: 'promote to fulfillment',
      }),
    onSuccess: () => invalidateMatching(),
  })

  const declineMutation = useMutation({
    mutationFn: (requestId: string) =>
      postDropMatchingResultDecline(requestId, {
        decision_reason: 'decline — not fulfill-ready',
      }),
    onSuccess: () => invalidateMatching(),
  })

  const assignMutation = useMutation({
    mutationFn: (requestIds: string[]) =>
      postDropWorkflowAssign({
        request_ids: requestIds,
        target_role: 'reviewer',
        assignee_identity: assigneeEmail.trim() || 'web-admin@habeas.com',
      }),
    onSuccess: () => {
      setCheckedIds(new Set())
      invalidateMatching()
    },
  })

  const bulkAssignMutation = useMutation({
    mutationFn: (matchType: MatchTypeFilter) =>
      postDropWorkflowAssignByMatchType({
        match_type: matchType,
        assignee_identity: assigneeEmail.trim() || 'web-admin@habeas.com',
        target_role: 'reviewer',
      }),
    onSuccess: () => {
      setCheckedIds(new Set())
      invalidateMatching()
    },
  })

  useEffect(() => {
    if (highlightRequestId) {
      setSelectedId(highlightRequestId)
      setView('detail')
    }
  }, [highlightRequestId])

  useEffect(() => {
    if (preferredBulkType) {
      setBulkType(preferredBulkType)
    }
  }, [preferredBulkType])

  useEffect(() => {
    if (focusBulk) {
      bulkSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [focusBulk])

  const stats = resultsQuery.data?.stats
  const rows = resultsQuery.data?.results ?? []
  const detail: MatchingResultDetail | undefined = detailQuery.data

  function openDetail(requestId: string) {
    setSelectedId(requestId)
    setView('detail')
  }

  function toggleChecked(requestId: string) {
    setCheckedIds((prev) => {
      const next = new Set(prev)
      if (next.has(requestId)) next.delete(requestId)
      else next.add(requestId)
      return next
    })
  }

  const selectedIds = [...checkedIds]
  const detailActionPending =
    promoteMutation.isPending ||
    declineMutation.isPending ||
    assignMutation.isPending

  const allVisibleSelected =
    rows.length > 0 && rows.every((row) => checkedIds.has(row.request_id))

  function toggleSelectAllVisible() {
    setCheckedIds((previous) => {
      if (allVisibleSelected) {
        const next = new Set(previous)
        for (const row of rows) next.delete(row.request_id)
        return next
      }
      const next = new Set(previous)
      for (const row of rows) next.add(row.request_id)
      return next
    })
  }

  return (
    <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
      <ConfirmActionDialog
        open={confirmBatchAssign}
        onOpenChange={setConfirmBatchAssign}
        title={`Assign all ${MATCH_TYPE_LABELS[bulkType]}?`}
        description={`Assign every DROP request in the ${MATCH_TYPE_LABELS[bulkType]} batch to ${assigneeEmail.trim() || 'the reviewer'}. Missing matching.review gates will be opened first.`}
        confirmLabel="Assign entire batch"
        confirming={bulkAssignMutation.isPending}
        onConfirm={() => {
          setConfirmBatchAssign(false)
          bulkAssignMutation.mutate(bulkType)
        }}
      />
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Micro>Matching results</Micro>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            Grouped by request. Promote clears matching.review for fulfillment; decline rejects
            without fulfilling. Assign routes the review to another operator (IAP actor).
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className={view === 'list' ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
            onClick={() => setView('list')}
          >
            List
          </button>
          <button
            type="button"
            className={view === 'detail' ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
            disabled={!selectedId}
            onClick={() => setView('detail')}
          >
            Detail
          </button>
        </div>
      </div>

      {stats && <StatsStrip stats={stats} />}

      {resultsQuery.isError && (
        <p className="text-sm text-red-700">Could not load matching results.</p>
      )}

      {view === 'list' && (
        <>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={listFilter === 'all' ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
              onClick={() => setListFilter('all')}
            >
              All
            </button>
            {MATCH_TYPE_OPTIONS.map((type) => (
              <button
                key={type}
                type="button"
                className={listFilter === type ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
                onClick={() => setListFilter(type)}
              >
                {MATCH_TYPE_LABELS[type]}
              </button>
            ))}
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
            <label className="flex min-w-[14rem] flex-1 flex-col gap-1 text-xs text-ink-soft">
              Request ID
              <input
                className="glass rounded-lg px-3 py-2 font-mono text-sm text-ink"
                value={requestIdQuery}
                onChange={(e) => setRequestIdQuery(e.target.value)}
                placeholder="Substring or prefix…"
                aria-label="Filter by request ID"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-soft">
              State
              <select
                className="glass rounded-lg px-3 py-2 text-sm text-ink"
                value={stateFilter}
                onChange={(e) => setStateFilter(e.target.value)}
                aria-label="Filter by requestor state"
              >
                <option value="all">All</option>
                {SERVED_STATE_ACRONYMS.map((state) => (
                  <option key={state} value={state}>
                    {state}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-soft">
              Recorded after
              <input
                type="date"
                className="glass rounded-lg px-3 py-2 text-sm text-ink"
                value={recordedAfter}
                onChange={(e) => setRecordedAfter(e.target.value)}
                aria-label="Recorded after date"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-soft">
              Recorded before
              <input
                type="date"
                className="glass rounded-lg px-3 py-2 text-sm text-ink"
                value={recordedBefore}
                onChange={(e) => setRecordedBefore(e.target.value)}
                aria-label="Recorded before date"
              />
            </label>
          </div>

          {selectedIds.length > 0 && (
            <div className="flex flex-col gap-3 rounded-lg border border-line p-4 sm:flex-row sm:flex-wrap sm:items-end">
              <p className="text-sm text-ink-soft">{selectedIds.length} selected</p>
              <label className="flex flex-col gap-1 text-xs text-ink-soft">
                Reviewer email
                <input
                  className="glass rounded-lg px-3 py-2 text-sm text-ink"
                  value={assigneeEmail}
                  onChange={(e) => setAssigneeEmail(e.target.value)}
                  placeholder="reviewer@habeas.com"
                  aria-label="Assignee email for assign"
                />
              </label>
              <button
                type="button"
                className="taste-btn-primary text-xs"
                disabled={assignMutation.isPending}
                onClick={() => assignMutation.mutate(selectedIds)}
              >
                {assignMutation.isPending ? 'Assigning…' : 'Assign to reviewer'}
              </button>
            </div>
          )}

          <div className="taste-panel overflow-x-auto px-2 py-1">
            {resultsQuery.isPending && <SkeletonLines lines={4} />}
            {resultsQuery.isSuccess && rows.length === 0 && (
              <p className="p-4 text-sm text-ink-soft">No matching results for this filter.</p>
            )}
            {rows.length > 0 && (
              <table className="taste-table">
                <thead>
                  <tr>
                    <th className="w-8">
                      <input
                        type="checkbox"
                        checked={allVisibleSelected}
                        onChange={toggleSelectAllVisible}
                        aria-label="Select all visible"
                      />
                    </th>
                    <th>Recorded</th>
                    <th>Request ID</th>
                    <th>State</th>
                    <th>Type</th>
                    <th>Count</th>
                    <th>Review</th>
                    <th>Assignment</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={`${row.request_id}-${row.recorded_at}`}
                      className="hover:bg-paper-raised/80"
                    >
                      <td>
                        <input
                          type="checkbox"
                          checked={checkedIds.has(row.request_id)}
                          onChange={() => toggleChecked(row.request_id)}
                          aria-label={`Select ${row.request_id}`}
                        />
                      </td>
                      <td
                        className="cursor-pointer"
                        onClick={() => openDetail(row.request_id)}
                      >
                        {row.recorded_at ? new Date(row.recorded_at).toLocaleString() : '—'}
                      </td>
                      <td
                        className="cursor-pointer font-mono text-xs"
                        onClick={() => openDetail(row.request_id)}
                      >
                        {row.request_id}
                      </td>
                      <td
                        className="cursor-pointer font-mono text-xs"
                        onClick={() => openDetail(row.request_id)}
                      >
                        {row.requestor_state ?? '—'}
                      </td>
                      <td
                        className="cursor-pointer"
                        onClick={() => openDetail(row.request_id)}
                      >
                        {MATCH_TYPE_LABELS[row.match_type]}
                      </td>
                      <td
                        className="cursor-pointer tabular-nums"
                        onClick={() => openDetail(row.request_id)}
                      >
                        {row.match_count}
                      </td>
                      <td
                        className="cursor-pointer"
                        onClick={() => openDetail(row.request_id)}
                      >
                        {row.review_status}
                      </td>
                      <td className="text-xs text-ink-soft">
                        {row.assignment
                          ? `${row.assignment.target_role}${row.assignment.assignee_identity
                            ? ` · ${row.assignment.assignee_identity}`
                            : ''
                          }`
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {assignMutation.isError && (
            <p className="text-sm text-red-700">
              {assignMutation.error instanceof Error
                ? assignMutation.error.message
                : String(assignMutation.error)}
            </p>
          )}
        </>
      )}

      {view === 'detail' && (
        <div className="taste-panel space-y-4 p-5">
          {!selectedId && <p className="text-sm text-ink-soft">Select a result from the list.</p>}
          {selectedId && detailQuery.isPending && <SkeletonLines lines={4} />}
          {selectedId && detailQuery.isError && (
            <p className="text-sm text-red-700">Could not load detail for this request.</p>
          )}
          {detail && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="font-mono text-xs text-ink-soft">{detail.request_id}</p>
                <button type="button" className="taste-btn text-xs" onClick={() => setView('list')}>
                  Back to list
                </button>
              </div>
              <dl className="grid gap-3 sm:grid-cols-2">
                <div>
                  <dt className="taste-micro">Match type</dt>
                  <dd className="mt-1 text-sm text-ink">{MATCH_TYPE_LABELS[detail.match_type]}</dd>
                </div>
                <div>
                  <dt className="taste-micro">Match count</dt>
                  <dd className="mt-1 tabular-nums text-sm text-ink">{detail.match_count}</dd>
                </div>
                <div>
                  <dt className="taste-micro">State</dt>
                  <dd className="mt-1 font-mono text-xs text-ink">
                    {detail.requestor_state ?? '—'}
                  </dd>
                </div>
                <div>
                  <dt className="taste-micro">Matched via</dt>
                  <dd className="mt-1 font-mono text-xs text-ink">{detail.matched_via}</dd>
                </div>
                <div>
                  <dt className="taste-micro">Review status</dt>
                  <dd className="mt-1 text-sm text-ink">{detail.review_status}</dd>
                </div>
                <div>
                  <dt className="taste-micro">Latest attempt</dt>
                  <dd className="mt-1 tabular-nums text-sm text-ink">{detail.attempt_id ?? '—'}</dd>
                </div>
                <div>
                  <dt className="taste-micro">Assignment</dt>
                  <dd className="mt-1 text-sm text-ink">
                    {detail.assignment
                      ? `${detail.assignment.kind ?? '—'} → ${detail.assignment.target_role}${detail.assignment.assignee_identity
                        ? ` (${detail.assignment.assignee_identity})`
                        : ''
                      }`
                      : '—'}
                  </dd>
                </div>
                <div>
                  <dt className="taste-micro">Recorded</dt>
                  <dd className="mt-1 text-sm text-ink">
                    {detail.recorded_at ? new Date(detail.recorded_at).toLocaleString() : '—'}
                  </dd>
                </div>
              </dl>

              <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
                <button
                  type="button"
                  className="taste-btn-primary"
                  disabled={detailActionPending}
                  onClick={() => promoteMutation.mutate(detail.request_id)}
                >
                  {promoteMutation.isPending ? 'Promoting…' : 'Promote to fulfillment'}
                </button>
                <button
                  type="button"
                  className="taste-btn"
                  disabled={detailActionPending}
                  onClick={() => declineMutation.mutate(detail.request_id)}
                >
                  {declineMutation.isPending ? 'Declining…' : 'Decline'}
                </button>
                <button
                  type="button"
                  className="taste-btn text-xs"
                  disabled={detailActionPending}
                  onClick={() => assignMutation.mutate([detail.request_id])}
                >
                  Assign to reviewer
                </button>
              </div>
              {(promoteMutation.isError || declineMutation.isError) && (
                <p className="text-sm text-red-700">
                  {(promoteMutation.error ?? declineMutation.error) instanceof Error
                    ? (promoteMutation.error ?? declineMutation.error)!.message
                    : String(promoteMutation.error ?? declineMutation.error)}
                </p>
              )}
              {promoteMutation.isSuccess && (
                <p className="text-sm text-emerald-700">Promoted — fulfill-ready when gate approved.</p>
              )}
              {declineMutation.isSuccess && (
                <p className="text-sm text-emerald-700">Declined — not fulfill-ready.</p>
              )}

              <AttemptHistory attempts={detail.attempts ?? []} />
            </>
          )}
        </div>
      )}

      <div ref={bulkSectionRef} className="border-t border-line pt-5">
        <Micro>Bulk by match type</Micro>
        <p className="mt-2 max-w-xl text-sm text-ink-soft">
          Acts on the entire DROP batch for the selected match type (not just checked rows).
          Promote/decline clear review gates; assign opens missing gates then routes the whole
          batch to a reviewer.
        </p>
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
          <select
            className="glass rounded-lg px-3 py-2 text-sm text-ink"
            value={bulkType}
            onChange={(event) => setBulkType(event.target.value as MatchTypeFilter)}
            aria-label="Bulk match type"
          >
            {MATCH_TYPE_OPTIONS.map((type) => (
              <option key={type} value={type}>
                {MATCH_TYPE_LABELS[type]}
              </option>
            ))}
          </select>
          <label className="flex min-w-[14rem] flex-col gap-1 text-xs text-ink-soft">
            Reviewer email
            <input
              className="glass rounded-lg px-3 py-2 text-sm text-ink"
              value={assigneeEmail}
              onChange={(e) => setAssigneeEmail(e.target.value)}
              placeholder="reviewer@habeas.com"
              aria-label="Assignee email for batch assign"
            />
          </label>
          <button
            type="button"
            className="taste-btn-primary"
            disabled={bulkPromoteMutation.isPending}
            onClick={() => bulkPromoteMutation.mutate(bulkType)}
          >
            {bulkPromoteMutation.isPending
              ? 'Promoting…'
              : `Promote ${MATCH_TYPE_LABELS[bulkType]}`}
          </button>
          <button
            type="button"
            className="taste-btn"
            disabled={bulkDeclineMutation.isPending}
            onClick={() => bulkDeclineMutation.mutate(bulkType)}
          >
            {bulkDeclineMutation.isPending
              ? 'Declining…'
              : `Decline ${MATCH_TYPE_LABELS[bulkType]}`}
          </button>
          <button
            type="button"
            className="taste-btn"
            disabled={
              bulkAssignMutation.isPending || assigneeEmail.trim().length === 0
            }
            onClick={() => setConfirmBatchAssign(true)}
          >
            {bulkAssignMutation.isPending
              ? 'Assigning…'
              : `Assign all ${MATCH_TYPE_LABELS[bulkType]}`}
          </button>
        </div>
        {bulkPromoteMutation.isSuccess && (
          <p className="mt-3 text-sm text-emerald-700">
            Promoted {bulkPromoteMutation.data.approved_count} pending review
            {bulkPromoteMutation.data.approved_count === 1 ? '' : 's'} for{' '}
            {bulkPromoteMutation.data.match_type}
            {bulkPromoteMutation.data.ensured_count
              ? ` (opened ${bulkPromoteMutation.data.ensured_count} missing gate${bulkPromoteMutation.data.ensured_count === 1 ? '' : 's'
              })`
              : ''}
            .
          </p>
        )}
        {bulkDeclineMutation.isSuccess && (
          <p className="mt-3 text-sm text-emerald-700">
            Declined {bulkDeclineMutation.data.declined_count} pending review
            {bulkDeclineMutation.data.declined_count === 1 ? '' : 's'} for{' '}
            {bulkDeclineMutation.data.match_type}.
          </p>
        )}
        {bulkAssignMutation.isSuccess && (
          <p className="mt-3 text-sm text-emerald-700">
            Assigned {bulkAssignMutation.data.count} request
            {bulkAssignMutation.data.count === 1 ? '' : 's'} (
            {MATCH_TYPE_LABELS[bulkAssignMutation.data.match_type]})
            {bulkAssignMutation.data.ensured_count
              ? ` · opened ${bulkAssignMutation.data.ensured_count} missing review gate${bulkAssignMutation.data.ensured_count === 1 ? '' : 's'
              }`
              : ''}
            .
          </p>
        )}
        {(bulkPromoteMutation.isError ||
          bulkDeclineMutation.isError ||
          bulkAssignMutation.isError) && (
            <p className="mt-3 text-sm text-red-700">
              {(bulkPromoteMutation.error ??
                bulkDeclineMutation.error ??
                bulkAssignMutation.error) instanceof Error
                ? (
                  bulkPromoteMutation.error ??
                  bulkDeclineMutation.error ??
                  bulkAssignMutation.error
                )!.message
                : String(
                  bulkPromoteMutation.error ??
                  bulkDeclineMutation.error ??
                  bulkAssignMutation.error,
                )}
            </p>
          )}
      </div>
    </div>
  )
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
  postMatchOpen,
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
    mutate: (
      action: { kind: 'enqueue'; state: string } | { kind: 'enqueue-all' } | { kind: 'process' },
    ) => void
  }
  actionMutation: { isPending: boolean }
  postMatchOpen: boolean
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-line bg-paper p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <Micro>Hash index refresh</Micro>
            <p className="mt-1 max-w-xl text-xs text-ink-soft">
              dbt rebuild per state, then rematch open not-found / multi-match DROP rows for that
              state.
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
                actionMutation.isPending ||
                postMatchOpen
              }
              onClick={() => hashIndexMutation.mutate({ kind: 'enqueue', state: hashState })}
            >
              Enqueue state
            </button>
            <button
              type="button"
              className="taste-btn px-3 py-1.5 text-xs"
              disabled={
                showSkeleton ||
                hashIndexMutation.isPending ||
                actionMutation.isPending ||
                postMatchOpen
              }
              onClick={() => hashIndexMutation.mutate({ kind: 'enqueue-all' })}
            >
              Enqueue all
            </button>
            <button
              type="button"
              className="taste-btn px-3 py-1.5 text-xs"
              disabled={
                showSkeleton ||
                !hashPending ||
                hashIndexMutation.isPending ||
                actionMutation.isPending ||
                postMatchOpen
              }
              onClick={() => hashIndexMutation.mutate({ kind: 'process' })}
            >
              Process
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
        <Link to="/ops/workers/$workerName" params={{ workerName: 'hash_index_refresh' }} className="text-[0.65rem] text-habeas-mid hover:underline">
          Worker →
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
  const { tab, process: processId } = useSearch({ from: '/' })
  const [lastAction, setLastAction] = useState<string | null>(null)
  const [actionResult, setActionResult] = useState<string | null>(null)
  const [postMatchOpen, setPostMatchOpen] = useState(false)
  const [postMatchSummary, setPostMatchSummary] = useState<string | null>(null)
  const [resultsFocusBulk, setResultsFocusBulk] = useState(false)
  const [highlightRequestId, setHighlightRequestId] = useState<string | null>(null)
  const [preferredBulkType, setPreferredBulkType] = useState<MatchTypeFilter | null>(null)
  const [hashState, setHashState] = useState('CA')
  const resultsAnchorRef = useRef<HTMLDivElement>(null)

  function setTab(next: PipelineTab) {
    void navigate({
      to: '/',
      search: { tab: next, process: processId },
    })
  }

  function setProcess(next: number | undefined) {
    void navigate({
      to: '/',
      search: { tab, process: next },
      replace: true,
    })
  }

  // Hard-block AppShell / in-page Links while the required post-match dialog is open.
  useBlocker({
    shouldBlockFn: () => true,
    disabled: !postMatchOpen,
    enableBeforeUnload: postMatchOpen,
  })

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

  // Default to the newest process when none selected.
  useEffect(() => {
    if (processId != null) return
    const newest = processList[0]?.process_id
    if (newest != null) setProcess(newest)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only auto-select when list arrives
  }, [processId, processList])

  // If URL process is stale/missing from recent list, fall back to latest.
  useEffect(() => {
    if (processId == null || processList.length === 0) return
    if (processList.some((item) => item.process_id === processId)) return
    setProcess(processList[0]?.process_id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processId, processList])

  const processDetailQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-processes', 'detail', processId],
    queryFn: () => getDropBulkProcess(processId!),
    enabled: processId != null,
    refetchInterval: 5_000,
    placeholderData: (previous) => previous,
  })

  const actionMutation = useMutation({
    mutationFn: async (key: ActionKey) => {
      const action = ACTIONS.find((item) => item.key === key)
      if (!action) throw new Error(`unknown action ${key}`)
      setLastAction(action.label)
      return { key, data: await action.run() }
    },
    onSuccess: ({ key, data }) => {
      setActionResult(JSON.stringify(data, null, 2))
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-processes'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-matching-results'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'approvals'] })
      if (key === 'match' && data && typeof data === 'object' && 'status' in data) {
        const status = String((data as { status?: unknown }).status ?? '')
        if (status === 'ok') {
          const requestId =
            'request_id' in data && typeof (data as { request_id?: unknown }).request_id === 'string'
              ? (data as { request_id: string }).request_id
              : null
          const matchCount =
            'match_count' in data && typeof (data as { match_count?: unknown }).match_count === 'number'
              ? (data as { match_count: number }).match_count
              : null
          setHighlightRequestId(requestId)
          setPreferredBulkType(matchCount == null ? null : matchTypeFromCount(matchCount))
          setPostMatchSummary(JSON.stringify(data, null, 2))
          setPostMatchOpen(true)
        }
      }
    },
    onError: (error) => {
      setActionResult(error instanceof Error ? error.message : String(error))
    },
  })

  const hashIndexMutation = useMutation({
    mutationFn: async (
      action: { kind: 'enqueue'; state: string } | { kind: 'enqueue-all' } | { kind: 'process' },
    ) => {
      if (action.kind === 'enqueue') {
        setLastAction(`Enqueue hash-index refresh (${action.state})`)
        return postHashIndexRefreshEnqueue({ state: action.state })
      }
      if (action.kind === 'enqueue-all') {
        setLastAction('Enqueue hash-index refresh (all states)')
        return postHashIndexRefreshEnqueueAll()
      }
      setLastAction('Process hash-index refresh')
      return postHashIndexRefreshProcess()
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
  const bulkDetail = processDetailQuery.data
  const approachingSla = approachingSlaFrom(data)
  const showSkeleton = pipelineQuery.isPending && !data
  const hashPending = (data?.hash_index_refresh?.pending ?? 0) > 0
  const hashWorkerDown = data ? !data.worker_health.hash_index_refresh?.ok : false
  const lastRun = data?.hash_index_refresh?.last_run
  const landQueue = summarizeIngestStep(data?.ingest_attempts ?? [], 'land')
  const promoteQueue = summarizeIngestStep(data?.ingest_attempts ?? [], 'promote')
  const fulfillmentUnset =
    data?.fulfillment?.response_status_null ??
    data?.raw_requests_by_list_type.reduce((sum, row) => sum + row.response_status_null, 0) ??
    0

  function handlePostMatchChoice(choice: PostMatchChoice) {
    setPostMatchOpen(false)
    setResultsFocusBulk(choice === 'bulk_approve')
    resultsAnchorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const showActionPanel =
    tab === 'download' ||
    tab === 'ingest' ||
    tab === 'matching' ||
    tab === 'fulfillment' ||
    tab === 'hash_refresh'

  const workersUp = data
    ? WORKER_ORDER.filter((name) => data.worker_health[name]?.ok).length
    : null
  const approachingDeadlineTotal = approachingSla
    ? approachingSla.connector +
    approachingSla.ingest +
    approachingSla.matching +
    approachingSla.matching_review
    : null
  const caSchedule = data?.ca_drop_schedule
  const matchTypeCounts = useMemo(() => {
    const counts = { single_match: 0, multi_match: 0, not_found: 0 }
    for (const row of data?.matching_results_recent ?? []) {
      const matchType = row.match_type
      if (matchType && matchType in counts) {
        counts[matchType as keyof typeof counts] += 1
      }
    }
    return counts
  }, [data?.matching_results_recent])
  const matchTypeMax = Math.max(
    1,
    matchTypeCounts.single_match,
    matchTypeCounts.multi_match,
    matchTypeCounts.not_found,
  )
  const slaBars = approachingSla
    ? [
      { key: 'Download', value: approachingSla.connector },
      { key: 'Ingest', value: approachingSla.ingest },
      { key: 'Matching', value: approachingSla.matching },
      { key: 'Review', value: approachingSla.matching_review },
    ]
    : []
  const slaMax = Math.max(1, ...slaBars.map((bar) => bar.value))

  return (
    <section className="space-y-5">
      <PostMatchDialog
        open={postMatchOpen}
        matchSummary={postMatchSummary}
        onChoose={handlePostMatchChoice}
      />

      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">Ops</p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight text-ink">Dashboard</h2>
        </div>
        {pipelineQuery.isFetching && !pipelineQuery.isPending ? (
          <span className="rounded-md border border-line px-2 py-0.5 text-[0.65rem] text-mute">
            Refreshing
          </span>
        ) : null}
      </header>

      <CompactOpsMetrics
        approachingDeadlineTotal={approachingDeadlineTotal}
        approachingReview={approachingSla?.matching_review ?? null}
        spineCount={data?.drop_requests.count ?? '—'}
        nextCaDrop={
          caSchedule?.next_run_at
            ? new Date(caSchedule.next_run_at).toLocaleString()
            : '—'
        }
        scheduleBlurb={
          caSchedule
            ? `${caSchedule.cadence} · ${caSchedule.schedule_utc} UTC`
            : 'Schedule unavailable'
        }
        reviewPending={data?.matching_review.pending ?? '—'}
        matchingQueue={data?.matching_attempts.pending ?? '—'}
        workersUp={workersUp}
        workersTotal={WORKER_ORDER.length}
      />

      <BulkProcessTracker
        processId={processId}
        onSelectProcess={setProcess}
        detail={bulkDetail}
        processes={processList}
        loading={processesQuery.isPending || processDetailQuery.isPending}
      />

      <PipelineTabBar active={tab} onSelect={setTab} />

      <BulkStepSummary tab={tab} detail={bulkDetail} />

      {showSkeleton && (
        <div
          className="rounded-lg border border-line bg-paper p-6"
          role="status"
          aria-label="Loading pipeline status"
        >
          <SkeletonLines lines={5} />
        </div>
      )}

      {pipelineQuery.isError && !data && (
        <p className="text-sm text-red-700">
          Could not load DROP pipeline status from admin-api.
        </p>
      )}

      {tab === 'home' && data ? (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-line bg-paper p-4">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Approaching age policy
              </p>
              <p className="mt-1 text-xs text-ink-soft">
                Open rows past stage attention thresholds (not legal SLA clocks).
              </p>
              <div className="mt-4 space-y-2.5">
                {slaBars.map((bar) => (
                  <div key={bar.key} className="grid grid-cols-[5rem_1fr_2rem] items-center gap-2">
                    <span className="text-[0.7rem] text-ink-soft">{bar.key}</span>
                    <div className="h-2 overflow-hidden rounded-full bg-panel">
                      <div
                        className="h-full rounded-full bg-habeas-mid"
                        style={{ width: `${(bar.value / slaMax) * 100}%` }}
                      />
                    </div>
                    <span className="text-right text-[0.7rem] tabular-nums text-ink">
                      {bar.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-line bg-paper p-4">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Recent match mix
              </p>
              <p className="mt-1 text-xs text-ink-soft">
                From latest matching_results sample on the pipeline snapshot.
              </p>
              <div className="mt-4 flex items-end gap-3" style={{ height: '7rem' }}>
                {(
                  [
                    ['Single', matchTypeCounts.single_match],
                    ['Multi', matchTypeCounts.multi_match],
                    ['Not found', matchTypeCounts.not_found],
                  ] as const
                ).map(([label, count]) => (
                  <div key={label} className="flex min-w-0 flex-1 flex-col items-center gap-1">
                    <span className="text-[0.65rem] tabular-nums text-mute">{count}</span>
                    <div className="flex w-full flex-1 items-end">
                      <div
                        className="w-full rounded-t-md bg-habeas-navy/80"
                        style={{
                          height: `${Math.max((count / matchTypeMax) * 100, count > 0 ? 8 : 0)}%`,
                        }}
                      />
                    </div>
                    <span className="truncate text-[0.65rem] text-ink-soft">{label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-line bg-paper">
            <div className="border-b border-line px-4 py-3">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Worker health
              </p>
            </div>
            <div className="overflow-x-auto px-2 py-1">
              <table className="taste-table">
                <thead>
                  <tr>
                    <th>Worker</th>
                    <th>Health</th>
                    <th>Code</th>
                    <th>Ready</th>
                  </tr>
                </thead>
                <tbody>
                  {WORKER_ORDER.map((name) => {
                    const probe = data.worker_health[name]
                    if (!probe) {
                      return (
                        <tr key={name}>
                          <td className="font-mono text-xs">{name}</td>
                          <td colSpan={3} className="text-mute">
                            —
                          </td>
                        </tr>
                      )
                    }
                    return <WorkerHealthRow key={name} probe={probe} />
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}

      {tab === 'history' && (
        <div className="space-y-3">
          <p className="text-xs text-ink-soft">
            Past bulk pipeline runs (intake + datetime). Select Track to drive the progress strip
            above.
          </p>
          <BatchRequestRunsList
            selectedProcessId={processId}
            onSelectProcess={(id) => setProcess(id)}
          />
        </div>
      )}

      {tab === 'download' && (
        <div className="space-y-3">
          <div className="rounded-md border border-line bg-paper p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <Micro>Download</Micro>
                <p className="mt-1 text-xs text-ink-soft">
                  Fetch the latest DROP ZIP from the connector worker.
                  {caSchedule?.next_run_at ? (
                    <>
                      {' '}
                      Next scheduled:{' '}
                      <span className="tabular-nums text-ink">
                        {new Date(caSchedule.next_run_at).toLocaleString()}
                      </span>
                    </>
                  ) : null}
                </p>
              </div>
              <ActionButtons
                keys={['download']}
                showSkeleton={showSkeleton}
                postMatchOpen={postMatchOpen}
                actionMutation={actionMutation}
              />
            </div>
            {approachingSla ? (
              <p className="mt-3 text-xs text-ink-soft">
                Approaching age policy:{' '}
                <span className="tabular-nums text-ink">{approachingSla.connector}</span> open
                past {approachingSla.thresholds_hours.connector}h
              </p>
            ) : null}
          </div>
          {data ? (
            <div className="rounded-md border border-line bg-paper p-3">
              <Micro>Connector attempts</Micro>
              <div className="mt-2">
                <CountTable rows={data.connector_attempts} empty="No connector attempts." />
              </div>
            </div>
          ) : null}
          <ProcessRunsHistoryPanel
            stage={TAB_HISTORY_STAGES.download!}
            days={7}
            emptyLabel="No download runs for bulk processes in this window."
          />
        </div>
      )}

      {tab === 'ingest' && (
        <div className="space-y-3">
          {approachingSla ? (
            <p className="text-xs text-ink-soft">
              Approaching age policy:{' '}
              <span className="tabular-nums text-ink">{approachingSla.ingest}</span> open past{' '}
              {approachingSla.thresholds_hours.ingest}h (land + promote)
            </p>
          ) : null}
          <div className="grid gap-3 lg:grid-cols-2">
            <div className="rounded-md border border-line bg-paper p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <Micro>Unzip</Micro>
                  <p className="mt-1 text-xs text-ink-soft">Land — unpack ZIP to staged CSVs.</p>
                </div>
                <ActionButtons
                  keys={['land']}
                  showSkeleton={showSkeleton}
                  postMatchOpen={postMatchOpen}
                  actionMutation={actionMutation}
                />
              </div>
              {data ? (
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-ink-soft">
                  <span>
                    Open <span className="tabular-nums text-ink">{landQueue.open}</span>
                  </span>
                  <span>
                    Failed{' '}
                    <span className={landQueue.failed > 0 ? 'tabular-nums text-red-700' : 'tabular-nums text-ink'}>
                      {landQueue.failed}
                    </span>
                  </span>
                  <span>
                    Success <span className="tabular-nums text-ink">{landQueue.success}</span>
                  </span>
                </div>
              ) : null}
            </div>

            <div className="rounded-md border border-line bg-paper p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <Micro>Promote to raw</Micro>
                  <p className="mt-1 text-xs text-ink-soft">Write staged rows into drop_raw_requests.</p>
                </div>
                <ActionButtons
                  keys={['promote']}
                  showSkeleton={showSkeleton}
                  postMatchOpen={postMatchOpen}
                  actionMutation={actionMutation}
                />
              </div>
              {data ? (
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-ink-soft">
                  <span>
                    Open <span className="tabular-nums text-ink">{promoteQueue.open}</span>
                  </span>
                  <span>
                    Failed{' '}
                    <span
                      className={
                        promoteQueue.failed > 0 ? 'tabular-nums text-red-700' : 'tabular-nums text-ink'
                      }
                    >
                      {promoteQueue.failed}
                    </span>
                  </span>
                  <span>
                    Success <span className="tabular-nums text-ink">{promoteQueue.success}</span>
                  </span>
                </div>
              ) : null}
            </div>
          </div>

          <ProcessRunsHistoryPanel
            stage={TAB_HISTORY_STAGES.ingest!}
            days={7}
            emptyLabel="No land/promote runs for bulk processes in this window."
          />

          {data ? (
            <div className="rounded-md border border-line bg-paper p-3">
              <Micro>Raw by list type</Micro>
              <div className="mt-2 overflow-x-auto">
                {data.raw_requests_by_list_type.length === 0 ? (
                  <p className="text-xs text-ink-soft">No drop_raw_requests rows.</p>
                ) : (
                  <table className="taste-table">
                    <thead>
                      <tr>
                        <th>List type</th>
                        <th>Total</th>
                        <th>response_status null</th>
                        <th>response_status set</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.raw_requests_by_list_type.map((row) => (
                        <tr key={row.list_type}>
                          <td className="font-mono text-xs">{row.list_type}</td>
                          <td className="tabular-nums">{row.total}</td>
                          <td className="tabular-nums">{row.response_status_null}</td>
                          <td className="tabular-nums">{row.response_status_set}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          ) : null}
        </div>
      )}

      {tab === 'matching' && (
        <>
          <div className="space-y-3">
            <div className="rounded-md border border-line bg-paper p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <Micro>Matching</Micro>
                  <p className="mt-1 max-w-xl text-xs text-ink-soft">
                    Dispatch thin requests, then run matching. Success opens a required review /
                    bulk-approve dialog.
                  </p>
                </div>
                <ActionButtons
                  keys={['dispatch', 'match']}
                  showSkeleton={showSkeleton}
                  postMatchOpen={postMatchOpen}
                  actionMutation={actionMutation}
                />
              </div>
              {approachingSla ? (
                <p className="mt-3 text-xs text-ink-soft">
                  Approaching: matching{' '}
                  <span className="tabular-nums text-ink">{approachingSla.matching}</span> (
                  {approachingSla.thresholds_hours.matching}h) · review{' '}
                  <span className="tabular-nums text-ink">{approachingSla.matching_review}</span>{' '}
                  ({approachingSla.thresholds_hours.matching_review}h)
                </p>
              ) : null}
            </div>
            <ProcessRunsHistoryPanel
              stage={TAB_HISTORY_STAGES.matching!}
              days={7}
              emptyLabel="No matching runs for bulk processes in this window."
            />
          </div>
          <div ref={resultsAnchorRef}>
            <MatchingResultsPanel
              focusBulk={resultsFocusBulk}
              highlightRequestId={highlightRequestId}
              preferredBulkType={preferredBulkType}
            />
          </div>
        </>
      )}

      {tab === 'fulfillment' && (
        <div className="space-y-3">
          <div className="rounded-md border border-line bg-paper p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <Micro>Fulfillment</Micro>
                <p className="mt-1 max-w-xl text-xs text-ink-soft">
                  Sets response_status (3/4/5) for DROP rows with approved matching.review. No
                  attempt-table runs — queue depth from the fulfillment worker.
                </p>
              </div>
              <ActionButtons
                keys={['fulfill']}
                showSkeleton={showSkeleton}
                postMatchOpen={postMatchOpen}
                actionMutation={actionMutation}
              />
            </div>
            {data ? (
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-ink-soft">
                <span>
                  Ready{' '}
                  <span className="tabular-nums text-ink">{data.fulfillment?.ready ?? '—'}</span>
                </span>
                <span>
                  Unset <span className="tabular-nums text-ink">{fulfillmentUnset}</span>
                </span>
                <span>
                  Review pending{' '}
                  <span className="tabular-nums text-ink">{data.matching_review.pending}</span>
                </span>
                <span>
                  Worker{' '}
                  <span
                    className={
                      data.worker_health.data_fulfillment?.ok
                        ? 'text-emerald-700'
                        : 'text-red-700'
                    }
                  >
                    {data.worker_health.data_fulfillment
                      ? data.worker_health.data_fulfillment.ok
                        ? 'up'
                        : 'down'
                      : '—'}
                  </span>
                </span>
              </div>
            ) : null}
          </div>

          <div className="rounded-md border border-line bg-paper">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
              <Micro>Worker queue</Micro>
              <Link
                to="/ops/workers/$workerName"
                params={{ workerName: 'data_fulfillment' }}
                className="text-[0.65rem] text-habeas-mid underline-offset-2 hover:underline"
              >
                data_fulfillment →
              </Link>
            </div>
            <p className="px-3 py-3 text-xs text-ink-soft">
              Fulfillment has no unified Runs rows yet — use Workers for live queue depth and
              probe status.
            </p>
          </div>

          {data ? (
            <div className="grid gap-3 lg:grid-cols-2">
              <div className="rounded-md border border-line bg-paper p-3">
                <Micro>response_status distribution</Micro>
                <p className="mt-1 text-[0.65rem] text-mute">
                  3 Deleted · 4 Opted out · 5 Not found
                </p>
                <div className="mt-2 overflow-x-auto">
                  <table className="taste-table">
                    <thead>
                      <tr>
                        <th>Status</th>
                        <th>Label</th>
                        <th>Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      {([null, 3, 4, 5] as const).map((code) => {
                        const count = data.fulfillment
                          ? countForResponseStatus(data.fulfillment.by_response_status, code)
                          : code == null
                            ? fulfillmentUnset
                            : 0
                        return (
                          <tr key={code ?? 'null'}>
                            <td className="font-mono text-xs">{code ?? 'null'}</td>
                            <td className="text-ink-soft">{responseStatusLabel(code)}</td>
                            <td className="tabular-nums">{count}</td>
                          </tr>
                        )
                      })}
                      {(data.fulfillment?.by_response_status ?? [])
                        .filter(
                          (row) =>
                            row.response_status != null &&
                            ![3, 4, 5].includes(row.response_status),
                        )
                        .map((row) => (
                          <tr key={`other-${row.response_status}`}>
                            <td className="font-mono text-xs">{row.response_status}</td>
                            <td className="text-ink-soft">
                              {responseStatusLabel(row.response_status)}
                            </td>
                            <td className="tabular-nums">{row.count}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="rounded-md border border-line bg-paper p-3">
                <Micro>Matching gate (fulfill blockers)</Micro>
                <div className="mt-2">
                  <StatusCountTable
                    rows={data.matching_review.by_status}
                    empty="No matching.review gates."
                  />
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}

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
          postMatchOpen={postMatchOpen}
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

      {showActionPanel ? (
        <ActionResultFrame
          lastAction={lastAction}
          actionResult={actionResult}
          onClear={() => {
            setLastAction(null)
            setActionResult(null)
          }}
        />
      ) : null}
    </section>
  )
}
