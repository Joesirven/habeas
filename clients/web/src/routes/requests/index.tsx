import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useMemo, useState } from 'react'

import { Skeleton } from '@/components/AppShell'
import {
  RequestDetailOverlay,
  useRequestDetailOverlay,
} from '@/components/requests/RequestDetailOverlay'
import { LegalChromeActions } from '@/components/UploadMenu'
import { Badge } from '@/components/ui/badge'
import {
  getDropGlobalStats,
  getNeedsAttention,
  listRequests,
  type IntakeSource,
  type RequestRecord,
} from '@/lib/api'
import { isLegalAdminPersona, useMe } from '@/lib/auth'
import { cn } from '@/lib/utils'
import type { RequestsSearch } from '@/router'

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

const SOURCE_OPTIONS: { value: '' | IntakeSource; label: string }[] = [
  { value: '', label: 'All sources' },
  { value: 'drop', label: 'CA DROP' },
  { value: 'webform', label: 'Gravity Forms' },
  { value: 'csv', label: 'Authorized Agent' },
  { value: 'manual', label: 'Manual' },
]

const VIEW_MODE_SESSION_KEY = 'requests-view-mode'

type ViewMode = 'flat' | 'batch'

type RequestBatch = {
  batchKey: string
  sourceLabel: string
  receivedAt: string
  requests: RequestRecord[]
}

function readViewMode(): ViewMode {
  try {
    return sessionStorage.getItem(VIEW_MODE_SESSION_KEY) === 'batch' ? 'batch' : 'flat'
  } catch {
    return 'flat'
  }
}

function requestBatchKey(request: RequestRecord): string {
  return `${request.intake_source}:${request.received_at.slice(0, 16)}`
}

function requestRowLabel(request: RequestRecord): string {
  const channel = SOURCE_LABELS[request.intake_source] ?? request.intake_source
  if (request.intake_source === 'drop') {
    return `${request.id} · ${channel}`
  }
  return request.display_label?.trim() || request.id
}

function RequestsTableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <table className="taste-table" role="status" aria-label="Loading requests">
      <thead>
        <tr>
          {Array.from({ length: 5 }, (_, index) => (
            <th key={index}>
              <Skeleton className="h-3 w-16" />
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, index) => (
          <tr key={index}>
            {Array.from({ length: 5 }, (_, cell) => (
              <td key={cell}>
                <Skeleton className="h-3.5 w-20" />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function StatTile({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-lg border border-line/80 bg-paper/60 px-4 py-3">
      <p className="taste-micro">{label}</p>
      <p className="mt-1 font-display text-2xl font-medium tabular-nums text-habeas-navy">
        {value}
      </p>
      {hint ? <p className="mt-1 text-[0.65rem] text-mute">{hint}</p> : null}
    </div>
  )
}

function matchesFilters(
  request: RequestRecord,
  search: RequestsSearch,
  attentionByRequestId: Map<string, string>,
  ephemeralSearch: string,
): boolean {
  if (search.source && request.intake_source !== search.source) return false
  if (search.source_bucket === 'drop' && request.intake_source !== 'drop') return false
  if (search.source_bucket === 'other' && request.intake_source === 'drop') return false
  if (search.request_type && request.request_type !== search.request_type) return false

  if (search.state) {
    const state = (request.requestor_state ?? '').toUpperCase()
    if (state !== search.state.toUpperCase()) return false
  }

  const needle = ephemeralSearch.trim().toLowerCase()
  if (needle) {
    if (request.id.toLowerCase().includes(needle)) return true
    if (request.intake_source === 'drop') return false
    if (request.display_label?.toLowerCase().includes(needle)) return true
    return false
  }

  if (search.raw === 'yes' && request.raw_record_id == null) return false
  if (search.raw === 'no' && request.raw_record_id != null) return false

  const hasAttention = attentionByRequestId.has(request.id)
  if (search.attention === 'needs' && !hasAttention) return false
  if (search.attention === 'clear' && hasAttention) return false

  if (search.received_after) {
    const after = new Date(search.received_after).getTime()
    if (!Number.isNaN(after) && new Date(request.received_at).getTime() < after) return false
  }
  if (search.received_before) {
    const before = new Date(search.received_before).getTime()
    if (!Number.isNaN(before) && new Date(request.received_at).getTime() > before) return false
  }

  return true
}

const POSTURE_LABELS: Record<NonNullable<RequestsSearch['posture']>, string> = {
  in_queue: 'In queue',
  in_progress: 'In progress',
  complete: 'Complete',
}

const DUE_LABELS: Record<NonNullable<RequestsSearch['due']>, string> = {
  overdue: 'Overdue',
  due_soon: 'Due within 7 days',
  on_track: 'On track',
}

function activeUrlFilterChips(search: RequestsSearch): { key: keyof RequestsSearch; label: string }[] {
  const chips: { key: keyof RequestsSearch; label: string }[] = []
  if (search.source) {
    chips.push({ key: 'source', label: SOURCE_LABELS[search.source] ?? search.source })
  }
  if (search.source_bucket === 'drop') chips.push({ key: 'source_bucket', label: 'DROP only' })
  if (search.source_bucket === 'other') chips.push({ key: 'source_bucket', label: 'Non-DROP' })
  if (search.request_type) chips.push({ key: 'request_type', label: search.request_type })
  if (search.stage) chips.push({ key: 'stage', label: `Stage: ${search.stage}` })
  if (search.posture) {
    chips.push({ key: 'posture', label: POSTURE_LABELS[search.posture] })
  }
  if (search.state) chips.push({ key: 'state', label: search.state })
  if (search.attention === 'needs') chips.push({ key: 'attention', label: 'Needs attention' })
  if (search.attention === 'clear') chips.push({ key: 'attention', label: 'No attention flag' })
  if (search.due) chips.push({ key: 'due', label: DUE_LABELS[search.due] })
  if (search.raw === 'yes') chips.push({ key: 'raw', label: 'Has raw record' })
  if (search.raw === 'no') chips.push({ key: 'raw', label: 'Missing raw record' })
  if (search.received_after) {
    chips.push({
      key: 'received_after',
      label: `After ${new Date(search.received_after).toLocaleString()}`,
    })
  }
  if (search.received_before) {
    chips.push({
      key: 'received_before',
      label: `Before ${new Date(search.received_before).toLocaleString()}`,
    })
  }
  return chips
}

function groupRequestsByBatch(requests: RequestRecord[]): RequestBatch[] {
  const batches = new Map<string, RequestBatch>()
  for (const request of requests) {
    const batchKey = requestBatchKey(request)
    const existing = batches.get(batchKey)
    if (existing) {
      existing.requests.push(request)
      continue
    }
    batches.set(batchKey, {
      batchKey,
      sourceLabel: SOURCE_LABELS[request.intake_source] ?? request.intake_source,
      receivedAt: request.received_at,
      requests: [request],
    })
  }
  return [...batches.values()].sort(
    (left, right) => new Date(right.receivedAt).getTime() - new Date(left.receivedAt).getTime(),
  )
}

function RequestRows({
  requests,
  attentionByRequestId,
  onOpen,
}: {
  requests: RequestRecord[]
  attentionByRequestId: Map<string, string>
  onOpen: (requestId: string, trigger?: HTMLElement | null, request?: RequestRecord) => void
}) {
  return (
    <>
      {requests.map((request) => {
        const attentionReason = attentionByRequestId.get(request.id)
        return (
          <tr
            key={request.id}
            className="group cursor-pointer transition-colors hover:bg-panel/50"
            onClick={(event) => onOpen(request.id, event.currentTarget, request)}
          >
            <td className="whitespace-nowrap tabular-nums text-ink-soft">
              {new Date(request.received_at).toLocaleString()}
            </td>
            <td>
              <span className="font-mono text-xs text-ink">{requestRowLabel(request)}</span>
            </td>
            <td>
              <span className="taste-frost-chip text-[0.65rem]">
                {SOURCE_LABELS[request.intake_source] ?? request.intake_source}
              </span>
            </td>
            <td className="font-mono text-xs">{request.requestor_state ?? '—'}</td>
            <td>
              {attentionReason ? (
                <Badge variant="fail" className="normal-case tracking-normal">
                  {attentionReason}
                </Badge>
              ) : (
                <span className="text-ink-soft">—</span>
              )}
            </td>
          </tr>
        )
      })}
    </>
  )
}

export function RequestsPage() {
  const navigate = useNavigate()
  const search = useSearch({ from: '/requests' })
  const { role } = useMe()
  const legalAdmin = isLegalAdminPersona(role)
  const [ephemeralSearch, setEphemeralSearch] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>(readViewMode)
  const overlay = useRequestDetailOverlay()

  useEffect(() => {
    try {
      sessionStorage.setItem(VIEW_MODE_SESSION_KEY, viewMode)
    } catch {
      // ignore storage failures
    }
  }, [viewMode])

  const listStage = search.stage

  const requestsQuery = useQuery({
    queryKey: [
      'admin-api',
      'requests',
      search.source ?? 'all',
      search.source_bucket ?? '',
      listStage ?? '',
      search.posture ?? '',
      ephemeralSearch.trim(),
    ],
    queryFn: () =>
      listRequests({
        intakeSource: search.source,
        sourceBucket: search.source_bucket,
        stage: listStage,
        posture: search.posture,
        limit: 100,
        q: ephemeralSearch.trim().length >= 2 ? ephemeralSearch.trim() : undefined,
      }),
    refetchInterval: 15_000,
  })

  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention'],
    queryFn: () => getNeedsAttention(200),
    refetchInterval: 15_000,
    staleTime: 10_000,
  })

  const statsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-stats-global'],
    queryFn: getDropGlobalStats,
    refetchInterval: 15_000,
    staleTime: 10_000,
  })

  const attentionByRequestId = useMemo(() => {
    const map = new Map<string, string>()
    for (const item of attentionQuery.data?.items ?? []) {
      map.set(item.request_id, item.reason)
    }
    return map
  }, [attentionQuery.data?.items])

  const stateOptions = useMemo(() => {
    const set = new Set<string>()
    for (const request of requestsQuery.data ?? []) {
      if (request.requestor_state) set.add(request.requestor_state.toUpperCase())
    }
    return [...set].sort()
  }, [requestsQuery.data])

  const filtered = useMemo(() => {
    const rows = requestsQuery.data ?? []
    return rows.filter((request) =>
      matchesFilters(request, search, attentionByRequestId, ephemeralSearch),
    )
  }, [requestsQuery.data, search, attentionByRequestId, ephemeralSearch])

  const batches = useMemo(() => groupRequestsByBatch(filtered), [filtered])

  function patchSearch(patch: Partial<RequestsSearch>) {
    void navigate({
      to: '/requests',
      search: {
        source: 'source' in patch ? patch.source : search.source,
        source_bucket: 'source_bucket' in patch ? patch.source_bucket : search.source_bucket,
        request_type: 'request_type' in patch ? patch.request_type : search.request_type,
        stage: 'stage' in patch ? patch.stage : search.stage,
        posture: 'posture' in patch ? patch.posture : search.posture,
        state: 'state' in patch ? patch.state : search.state,
        attention: 'attention' in patch ? patch.attention : search.attention,
        due: 'due' in patch ? patch.due : search.due,
        raw: 'raw' in patch ? patch.raw : search.raw,
        received_after: 'received_after' in patch ? patch.received_after : search.received_after,
        received_before:
          'received_before' in patch ? patch.received_before : search.received_before,
      },
      replace: true,
    })
  }

  function clearFilters() {
    void navigate({ to: '/requests', search: {}, replace: true })
  }

  function openTriage(requestId: string, trigger?: HTMLElement | null, request?: RequestRecord) {
    overlay.openOverlay(requestId, trigger, request)
  }

  const stats = statsQuery.data
  const activeFilterCount = [
    search.source,
    search.source_bucket,
    search.request_type,
    search.stage,
    search.posture,
    search.state,
    search.attention,
    search.due,
    search.raw,
    search.received_after,
    search.received_before,
  ].filter(Boolean).length
  const urlFilterChips = activeUrlFilterChips(search)

  const tableHeader = (
    <thead>
      <tr>
        <th>Received</th>
        <th>Request</th>
        <th>Source</th>
        <th>State</th>
        <th>Attention</th>
      </tr>
    </thead>
  )

  return (
    <section className="taste-ops-page space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="taste-micro">Requests</p>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              All requests
            </h2>
            {requestsQuery.isFetching && !requestsQuery.isPending && (
              <span className="taste-frost-chip text-[0.65rem]">Refreshing</span>
            )}
            {requestsQuery.isSuccess ? (
              <span className="taste-frost-chip tabular-nums text-[0.65rem]">
                {filtered.length}
                {filtered.length !== (requestsQuery.data?.length ?? 0)
                  ? ` / ${requestsQuery.data?.length}`
                  : ''}{' '}
                shown
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div
            className="inline-flex rounded-md border border-line bg-paper p-0.5"
            role="toolbar"
            aria-label="List view mode"
          >
            <button
              type="button"
              className={cn(
                'rounded px-2.5 py-1 text-[0.7rem] font-medium transition-colors',
                viewMode === 'flat'
                  ? 'bg-habeas-navy/8 text-habeas-navy'
                  : 'text-ink-soft hover:text-ink',
              )}
              onClick={() => setViewMode('flat')}
            >
              Flat list
            </button>
            <button
              type="button"
              className={cn(
                'rounded px-2.5 py-1 text-[0.7rem] font-medium transition-colors',
                viewMode === 'batch'
                  ? 'bg-habeas-navy/8 text-habeas-navy'
                  : 'text-ink-soft hover:text-ink',
              )}
              onClick={() => setViewMode('batch')}
            >
              By batch
            </button>
          </div>
          <Link to="/requests/needs-attention" className="taste-btn text-xs">
            Inbox
            {attentionQuery.data && attentionQuery.data.items.length > 0 ? (
              <span className="ml-1.5 tabular-nums text-[0.65rem] opacity-80">
                ({attentionQuery.data.items.length})
              </span>
            ) : null}
          </Link>
          {legalAdmin ? (
            <LegalChromeActions />
          ) : (
            <Link to="/requests/new" className="taste-btn-primary text-xs">
              Manual submit
            </Link>
          )}
        </div>
      </header>

      {stats ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <StatTile label="Open DROP requests" value={stats.open_drop_requests} />
          <StatTile label="Matching review pending" value={stats.matching_review_pending} />
          <StatTile
            label="Matching failed terminal"
            value={stats.matching_failed_terminal}
            hint={
              stats.workers_down > 0
                ? `${stats.workers_down}/${stats.workers_total} workers down`
                : undefined
            }
          />
        </div>
      ) : statsQuery.isPending ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="rounded-lg border border-line/80 bg-paper/60 px-4 py-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-3 h-7 w-12" />
            </div>
          ))}
        </div>
      ) : null}

      <div className="taste-panel space-y-3 p-3 sm:p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="taste-micro">Filters</p>
          {activeFilterCount > 0 ? (
            <button type="button" className="taste-link text-[0.7rem]" onClick={clearFilters}>
              Clear {activeFilterCount}
            </button>
          ) : null}
        </div>
        {urlFilterChips.length > 0 ? (
          <div className="flex flex-wrap gap-1.5" role="list" aria-label="Active URL filters">
            {urlFilterChips.map((chip) => (
              <button
                key={chip.key}
                type="button"
                role="listitem"
                className="inline-flex items-center gap-1 rounded-md border border-habeas-navy/25 bg-habeas-navy/8 px-2 py-0.5 text-[0.65rem] font-medium text-habeas-navy transition-colors hover:border-habeas-navy/40"
                onClick={() => patchSearch({ [chip.key]: undefined })}
              >
                {chip.label}
                <span aria-hidden className="text-[0.6rem] opacity-70">
                  ×
                </span>
              </button>
            ))}
          </div>
        ) : null}
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <label className="flex flex-col gap-1 text-[0.7rem] text-ink-soft">
            Source
            <select
              className="glass rounded-lg px-2 py-1.5 text-xs text-ink"
              value={search.source ?? ''}
              onChange={(event) =>
                patchSearch({
                  source: (event.target.value || undefined) as RequestsSearch['source'],
                })
              }
            >
              {SOURCE_OPTIONS.map((option) => (
                <option key={option.value || 'all'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[0.7rem] text-ink-soft">
            Requestor state
            <select
              className="glass rounded-lg px-2 py-1.5 text-xs text-ink"
              value={search.state ?? ''}
              onChange={(event) =>
                patchSearch({ state: event.target.value || undefined })
              }
            >
              <option value="">All states</option>
              {stateOptions.map((state) => (
                <option key={state} value={state}>
                  {state}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[0.7rem] text-ink-soft">
            Attention
            <select
              className="glass rounded-lg px-2 py-1.5 text-xs text-ink"
              value={search.attention ?? ''}
              onChange={(event) =>
                patchSearch({
                  attention: (event.target.value || undefined) as RequestsSearch['attention'],
                })
              }
            >
              <option value="">All</option>
              <option value="needs">Needs attention</option>
              <option value="clear">No attention flag</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[0.7rem] text-ink-soft">
            Raw record
            <select
              className="glass rounded-lg px-2 py-1.5 text-xs text-ink"
              value={search.raw ?? ''}
              onChange={(event) =>
                patchSearch({
                  raw: (event.target.value || undefined) as RequestsSearch['raw'],
                })
              }
            >
              <option value="">All</option>
              <option value="yes">Has raw record</option>
              <option value="no">Missing raw record</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[0.7rem] text-ink-soft sm:col-span-2">
            Name or request ID
            <input
              type="search"
              className="glass rounded-lg px-2 py-1.5 text-xs text-ink"
              placeholder="Search — not saved to URL"
              value={ephemeralSearch}
              onChange={(event) => setEphemeralSearch(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-[0.7rem] text-ink-soft">
            Received after
            <input
              type="datetime-local"
              className="glass rounded-lg px-2 py-1.5 font-mono text-xs text-ink"
              value={search.received_after?.slice(0, 16) ?? ''}
              onChange={(event) => {
                const value = event.target.value
                patchSearch({
                  received_after: value ? new Date(value).toISOString() : undefined,
                })
              }}
            />
          </label>
          <label className="flex flex-col gap-1 text-[0.7rem] text-ink-soft">
            Received before
            <input
              type="datetime-local"
              className="glass rounded-lg px-2 py-1.5 font-mono text-xs text-ink"
              value={search.received_before?.slice(0, 16) ?? ''}
              onChange={(event) => {
                const value = event.target.value
                patchSearch({
                  received_before: value ? new Date(value).toISOString() : undefined,
                })
              }}
            />
          </label>
        </div>
      </div>

      <div className="taste-panel overflow-hidden">
        {requestsQuery.isPending && <RequestsTableSkeleton />}
        {requestsQuery.isError && (
          <p className="p-4 text-xs text-red-700">
            Could not load requests. Is admin-api running with DATABASE_URL?
          </p>
        )}
        {requestsQuery.isSuccess && filtered.length === 0 && (
          <p className="p-4 text-xs text-ink-soft">
            {(requestsQuery.data?.length ?? 0) === 0
              ? 'No requests yet.'
              : 'No requests match the current filters.'}
          </p>
        )}
        {requestsQuery.isSuccess && filtered.length > 0 && viewMode === 'flat' && (
          <div className="overflow-x-auto">
            <table className="taste-table">
              {tableHeader}
              <tbody>
                <RequestRows
                  requests={filtered}
                  attentionByRequestId={attentionByRequestId}
                  onOpen={openTriage}
                />
              </tbody>
            </table>
          </div>
        )}
        {requestsQuery.isSuccess && filtered.length > 0 && viewMode === 'batch' && (
          <div className="divide-y divide-line/60">
            {batches.map((batch) => (
              <section key={batch.batchKey} className="p-3 sm:p-4">
                <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-xs font-medium text-ink">
                    {batch.sourceLabel} · {new Date(batch.receivedAt).toLocaleString()}
                  </h3>
                  <span className="taste-frost-chip tabular-nums text-[0.65rem]">
                    {batch.requests.length}
                  </span>
                </header>
                <div className="overflow-x-auto">
                  <table className="taste-table">
                    {tableHeader}
                    <tbody>
                      <RequestRows
                        requests={batch.requests}
                        attentionByRequestId={attentionByRequestId}
                        onOpen={openTriage}
                      />
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>
        )}
      </div>

      <RequestDetailOverlay
        requestId={overlay.requestId}
        open={overlay.open}
        onOpenChange={overlay.onOpenChange}
        returnFocusRef={overlay.returnFocusRef}
        seedRequest={overlay.seedRequest}
      />
    </section>
  )
}
