import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useBlocker, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { SkeletonLines } from '@/components/AppShell'
import {
  getDropMatchingResultDetail,
  getDropMatchingResults,
  getDropPipeline,
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
  postDropWorkflowEscalate,
  postHashIndexRefreshEnqueue,
  postHashIndexRefreshEnqueueAll,
  postHashIndexRefreshProcess,
  type DropPipelineStatus,
  type HashIndexRefreshStatus,
  type MatchTypeFilter,
  type MatchingAttemptRow,
  type MatchingResultDetail,
  type MatchingResultsStats,
  type StepStatusCount,
  type WorkerHealthProbe,
} from '@/lib/api'

type PipelineTab =
  | 'home'
  | 'download'
  | 'ingest'
  | 'matching'
  | 'fulfillment'
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

const PIPELINE_STAGES = [
  '01 Download',
  '02 Land',
  '03 Promote',
  '04 Match',
  '05 Review',
  '06 Fulfill',
] as const

const PIPELINE_TAB_BAR: { key: PipelineTab; label: string }[] = [
  { key: 'home', label: 'Home' },
  { key: 'download', label: 'Download' },
  { key: 'ingest', label: 'Ingest' },
  { key: 'matching', label: 'Matching' },
  { key: 'fulfillment', label: 'Fulfillment' },
]

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
  const tabs =
    active === 'configurations'
      ? [...PIPELINE_TAB_BAR, { key: 'configurations' as const, label: 'Configurations' }]
      : PIPELINE_TAB_BAR

  return (
    <div className="flex flex-wrap gap-2 border-b border-line pb-4">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          className={active === tab.key ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
          onClick={() => onSelect(tab.key)}
        >
          {tab.label}
        </button>
      ))}
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
    <div className="flex flex-col gap-2">
      {filtered.map((action, index) => {
        const busy = actionMutation.isPending && actionMutation.variables === action.key
        return (
          <button
            key={action.key}
            type="button"
            className={
              index === 0
                ? 'taste-btn-primary w-full justify-between gap-3 text-left'
                : 'taste-btn w-full justify-between gap-3 text-left'
            }
            disabled={actionMutation.isPending || showSkeleton || postMatchOpen}
            onClick={() => actionMutation.mutate(action.key)}
          >
            <span>{action.label}</span>
            {busy ? (
              <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            ) : (
              <span className="font-mono text-[0.65rem] opacity-50">
                {String(index + 1).padStart(2, '0')}
              </span>
            )}
          </button>
        )
      })}
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

function AtmospherePanel({ data }: { data: DropPipelineStatus | undefined }) {
  const workersUp = data
    ? WORKER_ORDER.filter((name) => data.worker_health[name]?.ok).length
    : 0

  return (
    <div className="relative min-h-[22rem] overflow-hidden rounded-[1.35rem] bg-habeas-navy">
      <div
        aria-hidden
        className="taste-atmosphere-orb pointer-events-none absolute -left-16 top-8 h-56 w-56 rounded-full bg-habeas-light/35 blur-2xl"
      />
      <div
        aria-hidden
        className="taste-atmosphere-orb pointer-events-none absolute -right-10 bottom-0 h-64 w-64 rounded-full bg-habeas-mid/45 blur-3xl"
        style={{ animationDelay: '1.6s' }}
      />
      <div
        aria-hidden
        className="taste-atmosphere-orb pointer-events-none absolute left-1/3 top-1/4 h-40 w-40 rounded-full bg-white/10 blur-xl"
        style={{ animationDelay: '3.2s' }}
      />

      <div className="relative flex h-full flex-col justify-between gap-8 p-6 sm:p-7">
        <div className="flex flex-wrap gap-2">
          <span className="taste-frost-chip-dark">Spine live</span>
          <span className="taste-frost-chip-dark">
            Workers {data ? `${workersUp}/${WORKER_ORDER.length}` : '—'}
          </span>
          <span className="taste-frost-chip-dark">
            Matching pending {data?.matching_review.pending ?? '—'}
          </span>
        </div>

        <div>
          <p className="text-[0.65rem] font-medium uppercase tracking-[0.18em] text-white/55">
            DROP requests
          </p>
          <p className="mt-2 font-display text-6xl font-medium tracking-tight text-white sm:text-7xl">
            {data?.drop_requests.count ?? '—'}
          </p>
          <p className="mt-3 max-w-xs text-sm leading-relaxed text-white/65">
            Thin intake rows in flight. Counts and ids only — no personally identifiable
            information.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <span className="taste-frost-chip-dark">
            Match success {data?.matching_attempts.success ?? '—'}
          </span>
          <span className="taste-frost-chip-dark">
            Review approved {data?.matching_review.approved ?? '—'}
          </span>
        </div>
      </div>
    </div>
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
  const [escalateTarget, setEscalateTarget] = useState<'legal' | 'data_owner'>('legal')
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

  const escalateMutation = useMutation({
    mutationFn: (requestIds: string[]) =>
      postDropWorkflowEscalate({
        request_ids: requestIds,
        target_role: escalateTarget,
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
    assignMutation.isPending ||
    escalateMutation.isPending

  return (
    <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Micro>Matching results</Micro>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            Grouped by request. Promote clears matching.review for fulfillment; decline rejects
            without fulfilling. Assign/escalate uses IAP identity for the actor.
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
              <select
                className="glass rounded-lg px-3 py-2 text-sm text-ink"
                value={escalateTarget}
                onChange={(e) => setEscalateTarget(e.target.value as 'legal' | 'data_owner')}
                aria-label="Escalate target"
              >
                <option value="legal">Legal</option>
                <option value="data_owner">Data owner</option>
              </select>
              <button
                type="button"
                className="taste-btn text-xs"
                disabled={escalateMutation.isPending}
                onClick={() => escalateMutation.mutate(selectedIds)}
              >
                {escalateMutation.isPending ? 'Escalating…' : `Escalate to ${escalateTarget}`}
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
                    <th className="w-8" aria-label="Select" />
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
                          ? `${row.assignment.target_role}${
                              row.assignment.assignee_identity
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
          {(assignMutation.isError || escalateMutation.isError) && (
            <p className="text-sm text-red-700">
              {(assignMutation.error ?? escalateMutation.error) instanceof Error
                ? (assignMutation.error ?? escalateMutation.error)!.message
                : String(assignMutation.error ?? escalateMutation.error)}
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
                      ? `${detail.assignment.kind ?? '—'} → ${detail.assignment.target_role}${
                          detail.assignment.assignee_identity
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
                <select
                  className="glass rounded-lg px-3 py-2 text-sm text-ink"
                  value={escalateTarget}
                  onChange={(e) => setEscalateTarget(e.target.value as 'legal' | 'data_owner')}
                  aria-label="Escalate target detail"
                >
                  <option value="legal">Legal</option>
                  <option value="data_owner">Data owner</option>
                </select>
                <button
                  type="button"
                  className="taste-btn text-xs"
                  disabled={detailActionPending}
                  onClick={() => escalateMutation.mutate([detail.request_id])}
                >
                  Escalate
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
        <Micro>Bulk promote / decline</Micro>
        <p className="mt-2 max-w-xl text-sm text-ink-soft">
          Promote ensures matching.review gates and approves them for the match type (including
          multi-match). Decline rejects pending gates without fulfilling.
        </p>
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
          <select
            className="glass rounded-lg px-3 py-2 text-sm text-ink"
            value={bulkType}
            onChange={(event) => setBulkType(event.target.value as MatchTypeFilter)}
            aria-label="Bulk promote match type"
          >
            {MATCH_TYPE_OPTIONS.map((type) => (
              <option key={type} value={type}>
                {MATCH_TYPE_LABELS[type]}
              </option>
            ))}
          </select>
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
        </div>
        {bulkPromoteMutation.isSuccess && (
          <p className="mt-3 text-sm text-emerald-700">
            Promoted {bulkPromoteMutation.data.approved_count} pending review
            {bulkPromoteMutation.data.approved_count === 1 ? '' : 's'} for{' '}
            {bulkPromoteMutation.data.match_type}
            {bulkPromoteMutation.data.ensured_count
              ? ` (opened ${bulkPromoteMutation.data.ensured_count} missing gate${
                  bulkPromoteMutation.data.ensured_count === 1 ? '' : 's'
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
        {(bulkPromoteMutation.isError || bulkDeclineMutation.isError) && (
          <p className="mt-3 text-sm text-red-700">
            {(bulkPromoteMutation.error ?? bulkDeclineMutation.error) instanceof Error
              ? (bulkPromoteMutation.error ?? bulkDeclineMutation.error)!.message
              : String(bulkPromoteMutation.error ?? bulkDeclineMutation.error)}
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
    <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
      <div>
        <Micro>Hash index refresh</Micro>
        <p className="mt-2 max-w-xl text-sm text-ink-soft">
          Rebuild serving marts per state via dbt, then rematch open not-found and prior multi-match
          DROP requests for that state. Enqueue queues one attempt; enqueue all covers USPS 50+DC.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-ink-soft">
          <span className="taste-micro">State</span>
          <select
            className="glass rounded-lg px-3 py-2 font-mono text-sm text-ink"
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
        <span className="text-sm text-ink-soft">
          {hashWorkerDown
            ? 'Worker down'
            : hashPending
              ? 'Pending / in-flight'
              : lastRun
                ? `Last ${lastRun.status}`
                : 'None'}
        </span>
        {lastRun?.status === 'success' && (
          <span className="text-sm text-ink-soft">
            rows e/p/n {lastRun.rows_email ?? '—'}/{lastRun.rows_phone ?? '—'}/
            {lastRun.rows_ndz ?? '—'} · rematch {lastRun.rematch_enqueued_count}
          </span>
        )}
        {lastRun?.status && lastRun.status !== 'success' && lastRun.error_message && (
          <span className="text-sm text-red-700">{lastRun.error_message}</span>
        )}
      </div>
      <div>
        <Micro>Attempts by status</Micro>
        <p className="mt-1 text-xs text-mute">
          Immutable attempt history counts — pending through terminal statuses.
        </p>
        <div className="mt-3">
          <StatusCountTable
            rows={data?.hash_index_refresh?.attempts_by_status ?? []}
            empty="No hash-index refresh attempts yet."
          />
        </div>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:gap-3">
        <button
          type="button"
          className="taste-btn"
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
          className="taste-btn"
          disabled={
            showSkeleton ||
            hashIndexMutation.isPending ||
            actionMutation.isPending ||
            postMatchOpen
          }
          onClick={() => hashIndexMutation.mutate({ kind: 'enqueue-all' })}
        >
          Enqueue all states
        </button>
        <button
          type="button"
          className="taste-btn"
          disabled={
            showSkeleton ||
            !hashPending ||
            hashIndexMutation.isPending ||
            actionMutation.isPending ||
            postMatchOpen
          }
          onClick={() => hashIndexMutation.mutate({ kind: 'process' })}
        >
          Process refresh
        </button>
      </div>
    </div>
  )
}

export function DropPipelinePage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { tab } = useSearch({ from: '/ops/drop-pipeline' })
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
    void navigate({ to: '/ops/drop-pipeline', search: { tab: next } })
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
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-stats-global'] })
    },
    onError: (error) => {
      setActionResult(error instanceof Error ? error.message : String(error))
    },
  })

  const data: DropPipelineStatus | undefined = pipelineQuery.data
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
    tab === 'download' || tab === 'ingest' || tab === 'matching' || tab === 'fulfillment'

  return (
    <section className="space-y-16">
      <PostMatchDialog
        open={postMatchOpen}
        matchSummary={postMatchSummary}
        onChoose={handlePostMatchChoice}
      />

      <header className="grid gap-10 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
        <div>
          <Micro>Operations</Micro>
          <h2 className="mt-4 max-w-md font-display text-[3.25rem] font-medium leading-[1.02] tracking-tight text-ink sm:text-[3.75rem]">
            DROP
            <br />
            pipeline
          </h2>
        </div>
        <div className="border-l border-line pl-5">
          <p className="max-w-sm text-sm leading-relaxed text-ink-soft">
            Super-admin console for DROP download → unzip/promote to raw → match → matching review →
            fulfill. Counts and ids only.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            {PIPELINE_STAGES.map((stage) => (
              <span
                key={stage}
                className="glass px-2.5 py-1 font-mono text-[0.65rem] uppercase tracking-[0.08em] text-ink-soft"
              >
                {stage}
              </span>
            ))}
          </div>
        </div>
      </header>

      <PipelineTabBar active={tab} onSelect={setTab} />

      {showSkeleton && (
        <div className="taste-panel p-6" role="status" aria-label="Loading pipeline status">
          <SkeletonLines lines={5} />
        </div>
      )}

      {pipelineQuery.isError && !data && (
        <p className="text-sm text-red-700">
          Could not load DROP pipeline status. Is admin-api running with DATABASE_URL?
        </p>
      )}

      {tab === 'home' && (
        <>
          <div className="grid items-start gap-6 lg:grid-cols-[0.95fr_1.05fr]">
            <div className="taste-panel-soft flex min-w-0 flex-col gap-6 p-6 sm:p-7">
              <div>
                <Micro>Overview</Micro>
                <p className="mt-2 max-w-sm text-sm text-ink-soft">
                  Spine snapshot across review, matching, and intake. Use stage tabs to run actions.
                </p>
              </div>
              {data ? (
                <div className="overflow-x-auto">
                  <table className="taste-table">
                    <tbody>
                      <tr>
                        <td className="!px-0 text-ink-soft">Matching review pending</td>
                        <td className="!px-0 tabular-nums">{data.matching_review.pending}</td>
                      </tr>
                      <tr>
                        <td className="!px-0 text-ink-soft">Matching attempts pending</td>
                        <td className="!px-0 tabular-nums">{data.matching_attempts.pending}</td>
                      </tr>
                      {approachingSla ? (
                        <>
                          <tr>
                            <td className="!px-0 text-ink-soft">
                              Download approaching (age policy)
                            </td>
                            <td className="!px-0 tabular-nums">
                              {approachingSla.connector}
                            </td>
                          </tr>
                          <tr>
                            <td className="!px-0 text-ink-soft">
                              Ingest approaching (age policy)
                            </td>
                            <td className="!px-0 tabular-nums">{approachingSla.ingest}</td>
                          </tr>
                          <tr>
                            <td className="!px-0 text-ink-soft">
                              Matching approaching (age policy)
                            </td>
                            <td className="!px-0 tabular-nums">
                              {approachingSla.matching}
                            </td>
                          </tr>
                          <tr>
                            <td className="!px-0 text-ink-soft">
                              Review approaching (age policy)
                            </td>
                            <td className="!px-0 tabular-nums">
                              {approachingSla.matching_review}
                            </td>
                          </tr>
                        </>
                      ) : null}
                      <tr>
                        <td className="!px-0 text-ink-soft">DROP requests</td>
                        <td className="!px-0 tabular-nums">{data.drop_requests.count}</td>
                      </tr>
                      <tr>
                        <td className="!px-0 text-ink-soft">Hash refresh pending</td>
                        <td className="!px-0 tabular-nums">{data.hash_index_refresh?.pending ?? 0}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              ) : null}
              <Link to="/approvals/matching-review" className="taste-btn w-fit text-xs">
                Matching review →
              </Link>
            </div>
            <AtmospherePanel data={data} />
          </div>

          {data ? (
            <>
              <div className="space-y-3">
                <Micro>Worker health</Micro>
                <div className="taste-panel overflow-x-auto px-2 py-1">
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

              <div className="space-y-3">
                <Micro>Recent DROP requests</Micro>
                <div className="taste-panel overflow-x-auto px-2 py-1">
                  {data.drop_requests.recent.length === 0 ? (
                    <p className="p-4 text-sm text-ink-soft">No DROP thin requests yet.</p>
                  ) : (
                    <table className="taste-table">
                      <thead>
                        <tr>
                          <th>Received</th>
                          <th>Request ID</th>
                          <th>Raw record</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.drop_requests.recent.map((row) => (
                          <tr key={row.id}>
                            <td>
                              {row.received_at ? new Date(row.received_at).toLocaleString() : '—'}
                            </td>
                            <td className="font-mono text-xs">{row.id}</td>
                            <td className="tabular-nums">{row.raw_record_id ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            </>
          ) : null}
        </>
      )}

      {tab === 'download' && (
        <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="taste-panel-soft flex flex-col gap-6 p-6 sm:p-7">
            <div>
              <Micro>Download</Micro>
              <p className="mt-2 text-sm text-ink-soft">
                Fetch the latest DROP ZIP from the connector worker.
              </p>
            </div>
            <ActionButtons
              keys={['download']}
              showSkeleton={showSkeleton}
              postMatchOpen={postMatchOpen}
              actionMutation={actionMutation}
            />
          </div>
          {data ? (
            <div className="space-y-3">
              <Micro>Connector attempts</Micro>
              <div className="taste-panel-soft p-4">
                <CountTable rows={data.connector_attempts} empty="No connector attempts." />
              </div>
              {approachingSla ? (
                <div className="taste-panel-soft p-4">
                  <Micro>Approaching (age policy)</Micro>
                  <p className="mt-1 text-xs text-ink-soft">
                    Open connector attempts older than{' '}
                    {approachingSla.thresholds_hours.connector}h — not legal DROP deadline
                    clocks.
                  </p>
                  <table className="taste-table mt-3">
                    <tbody>
                      <tr>
                        <td className="!px-0 text-ink-soft">Connector</td>
                        <td className="!px-0 tabular-nums">{approachingSla.connector}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      )}

      {tab === 'ingest' && (
        <div className="space-y-6">
          {approachingSla ? (
            <div className="taste-panel-soft p-4">
              <Micro>Approaching (age policy)</Micro>
              <p className="mt-1 text-xs text-ink-soft">
                Open ingest attempts older than {approachingSla.thresholds_hours.ingest}h —
                age policy, not legal DROP deadline clocks.
              </p>
              <table className="taste-table mt-3">
                <tbody>
                  <tr>
                    <td className="!px-0 text-ink-soft">Ingest (land + promote)</td>
                    <td className="!px-0 tabular-nums">{approachingSla.ingest}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          ) : null}
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
              <div>
                <Micro>Unzip</Micro>
                <p className="mt-2 text-sm text-ink-soft">
                  Land step — unpack the DROP ZIP into staged CSVs.
                </p>
              </div>
              {data ? (
                <div className="flex flex-wrap gap-2">
                  <span className="glass px-2.5 py-1 text-xs text-ink-soft">
                    Open / pending{' '}
                    <span className="tabular-nums text-ink">{landQueue.open}</span>
                  </span>
                  <span className="glass px-2.5 py-1 text-xs text-ink-soft">
                    Failed / needs attention{' '}
                    <span
                      className={
                        landQueue.failed > 0
                          ? 'tabular-nums text-red-700'
                          : 'tabular-nums text-ink'
                      }
                    >
                      {landQueue.failed}
                    </span>
                  </span>
                  <span className="glass px-2.5 py-1 text-xs text-ink-soft">
                    Success <span className="tabular-nums text-ink">{landQueue.success}</span>
                  </span>
                </div>
              ) : null}
              <ActionButtons
                keys={['land']}
                showSkeleton={showSkeleton}
                postMatchOpen={postMatchOpen}
                actionMutation={actionMutation}
              />
              {data ? (
                <div>
                  <Micro>Attempts by status</Micro>
                  <div className="mt-3">
                    <StatusCountTable rows={landQueue.rows} empty="No land attempts." />
                  </div>
                </div>
              ) : null}
            </div>

            <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
              <div>
                <Micro>Promote to raw</Micro>
                <p className="mt-2 text-sm text-ink-soft">
                  Promote step — write staged rows into drop_raw_requests.
                </p>
              </div>
              {data ? (
                <div className="flex flex-wrap gap-2">
                  <span className="glass px-2.5 py-1 text-xs text-ink-soft">
                    Open / pending{' '}
                    <span className="tabular-nums text-ink">{promoteQueue.open}</span>
                  </span>
                  <span className="glass px-2.5 py-1 text-xs text-ink-soft">
                    Failed / needs attention{' '}
                    <span
                      className={
                        promoteQueue.failed > 0
                          ? 'tabular-nums text-red-700'
                          : 'tabular-nums text-ink'
                      }
                    >
                      {promoteQueue.failed}
                    </span>
                  </span>
                  <span className="glass px-2.5 py-1 text-xs text-ink-soft">
                    Success <span className="tabular-nums text-ink">{promoteQueue.success}</span>
                  </span>
                </div>
              ) : null}
              <ActionButtons
                keys={['promote']}
                showSkeleton={showSkeleton}
                postMatchOpen={postMatchOpen}
                actionMutation={actionMutation}
              />
              {data ? (
                <div>
                  <Micro>Attempts by status</Micro>
                  <div className="mt-3">
                    <StatusCountTable rows={promoteQueue.rows} empty="No promote attempts." />
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {data ? (
            <div className="space-y-3">
              <Micro>Raw by list type</Micro>
              <div className="taste-panel overflow-x-auto px-2 py-1">
                {data.raw_requests_by_list_type.length === 0 ? (
                  <p className="p-4 text-sm text-ink-soft">No drop_raw_requests rows.</p>
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
          <div className="grid items-start gap-6 lg:grid-cols-[0.9fr_1.1fr]">
            <div className="taste-panel-soft flex max-w-xl flex-col gap-6 p-6 sm:p-7">
              <div>
                <Micro>Matching</Micro>
                <p className="mt-2 text-sm text-ink-soft">
                  Dispatch thin requests to the matcher, then run matching. After success, the
                  required dialog forces review or bulk approve.
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
              <div className="taste-panel-soft flex flex-col gap-4 p-6 sm:p-7">
                <div>
                  <Micro>Approaching (age policy)</Micro>
                  <p className="mt-2 max-w-md text-sm text-ink-soft">
                    Open work older than stage age thresholds — not legal DROP deadline breach
                    clocks. Thresholds: matching {approachingSla.thresholds_hours.matching}h ·
                    review {approachingSla.thresholds_hours.matching_review}h.
                  </p>
                </div>
                <div className="overflow-x-auto">
                  <table className="taste-table">
                    <thead>
                      <tr>
                        <th className="!px-0">Stage</th>
                        <th className="!px-0">Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td className="!px-0 text-ink-soft">Matching attempts</td>
                        <td className="!px-0 tabular-nums">{approachingSla.matching}</td>
                      </tr>
                      <tr>
                        <td className="!px-0 text-ink-soft">Matching review</td>
                        <td className="!px-0 tabular-nums">
                          {approachingSla.matching_review}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
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
        <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="taste-panel-soft flex flex-col gap-6 p-6 sm:p-7">
            <div>
              <Micro>Fulfillment</Micro>
              <p className="mt-2 text-sm text-ink-soft">
                Dispatch sets response_status (3/4/5) for DROP rows with approved matching.review.
                Counts only — no request-id queue table on this worker.
              </p>
            </div>
            {data ? (
              <div className="flex flex-wrap gap-2">
                <span className="glass px-2.5 py-1 text-xs text-ink-soft">
                  Ready{' '}
                  <span className="tabular-nums text-ink">
                    {data.fulfillment?.ready ?? '—'}
                  </span>
                </span>
                <span className="glass px-2.5 py-1 text-xs text-ink-soft">
                  Unset <span className="tabular-nums text-ink">{fulfillmentUnset}</span>
                </span>
                <span className="glass px-2.5 py-1 text-xs text-ink-soft">
                  Review pending{' '}
                  <span className="tabular-nums text-ink">{data.matching_review.pending}</span>
                </span>
                <span className="glass px-2.5 py-1 text-xs text-ink-soft">
                  Review approved{' '}
                  <span className="tabular-nums text-ink">{data.matching_review.approved}</span>
                </span>
                <span className="glass px-2.5 py-1 text-xs text-ink-soft">
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
            <ActionButtons
              keys={['fulfill']}
              showSkeleton={showSkeleton}
              postMatchOpen={postMatchOpen}
              actionMutation={actionMutation}
            />
          </div>

          {data ? (
            <div className="space-y-6">
              <div className="space-y-3">
                <Micro>response_status distribution</Micro>
                <p className="text-xs text-mute">
                  CPPA codes on drop_raw_requests — 3 Deleted · 4 Opted out · 5 Not found.
                </p>
                <div className="taste-panel overflow-x-auto px-2 py-1">
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

              <div className="space-y-3">
                <Micro>Matching gate (fulfill blockers)</Micro>
                <div className="taste-panel-soft p-4">
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

      {tab === 'configurations' && (
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

      {showActionPanel || tab === 'configurations' ? (
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
