import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useMemo, useState } from 'react'

import { Skeleton } from '@/components/AppShell'
import { RequestDetailDrawer } from '@/components/requests/RequestTriageDialog'
import { UploadMenu } from '@/components/UploadMenu'
import { Badge } from '@/components/ui/badge'
import {
  getDropGlobalStats,
  getNeedsAttention,
  listRequests,
  type IntakeSource,
  type RequestRecord,
} from '@/lib/api'
import { isLegalAdminPersona, useMe } from '@/lib/auth'
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

function RequestsTableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <table className="taste-table" role="status" aria-label="Loading requests">
      <thead>
        <tr>
          {Array.from({ length: 6 }, (_, index) => (
            <th key={index}>
              <Skeleton className="h-3 w-16" />
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, index) => (
          <tr key={index}>
            {Array.from({ length: 6 }, (_, cell) => (
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
): boolean {
  if (search.source && request.intake_source !== search.source) return false

  if (search.request_type && request.request_type !== search.request_type) return false

  if (search.state) {
    const state = (request.requestor_state ?? '').toUpperCase()
    if (state !== search.state.toUpperCase()) return false
  }

  if (search.q) {
    const needle = search.q.trim().toLowerCase()
    if (!needle) return true
    if (request.id.toLowerCase().includes(needle)) return true
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

export function RequestsPage() {
  const navigate = useNavigate()
  const search = useSearch({ from: '/requests' })
  const { role } = useMe()
  const legalAdmin = isLegalAdminPersona(role)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogRequestId, setDialogRequestId] = useState<string | null>(null)

  const requestsQuery = useQuery({
    queryKey: [
      'admin-api',
      'requests',
      search.source ?? 'all',
      search.source_bucket ?? '',
      search.stage ?? '',
      search.posture ?? '',
      search.q ?? '',
    ],
    queryFn: () =>
      listRequests({
        intakeSource: search.source,
        sourceBucket: search.source_bucket,
        stage: search.stage,
        posture: search.posture,
        limit: 100,
        q: search.q,
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
    return rows.filter((request) => matchesFilters(request, search, attentionByRequestId))
  }, [requestsQuery.data, search, attentionByRequestId])

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
        raw: 'raw' in patch ? patch.raw : search.raw,
        q: 'q' in patch ? patch.q : search.q,
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

  function openTriage(requestId: string) {
    setDialogRequestId(requestId)
    setDialogOpen(true)
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
    search.raw,
    search.q,
    search.received_after,
    search.received_before,
  ].filter(Boolean).length

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
          <Link to="/requests/needs-attention" className="taste-btn text-xs">
            Inbox
            {attentionQuery.data && attentionQuery.data.items.length > 0 ? (
              <span className="ml-1.5 tabular-nums text-[0.65rem] opacity-80">
                ({attentionQuery.data.items.length})
              </span>
            ) : null}
          </Link>
          {legalAdmin ? (
            <UploadMenu />
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
              placeholder="Name or request ID"
              value={search.q ?? ''}
              onChange={(event) => patchSearch({ q: event.target.value || undefined })}
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
        {requestsQuery.isSuccess && filtered.length > 0 && (
          <div className="overflow-x-auto">
            <table className="taste-table">
              <thead>
                <tr>
                  <th>Received</th>
                  <th>Source</th>
                  <th>State</th>
                  {legalAdmin ? <th>Name</th> : null}
                  <th>Request ID</th>
                  <th>Raw record</th>
                  <th>Attention</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((request) => {
                  const attentionReason = attentionByRequestId.get(request.id)
                  return (
                    <tr
                      key={request.id}
                      className="group cursor-pointer transition-colors hover:bg-panel/50"
                      onClick={() => openTriage(request.id)}
                    >
                      <td className="whitespace-nowrap tabular-nums text-ink-soft">
                        {new Date(request.received_at).toLocaleString()}
                      </td>
                      <td>
                        <span className="taste-frost-chip text-[0.65rem]">
                          {SOURCE_LABELS[request.intake_source] ?? request.intake_source}
                        </span>
                      </td>
                      <td className="font-mono text-xs">
                        {request.requestor_state ?? '—'}
                      </td>
                      {legalAdmin ? (
                        <td className="text-xs text-ink-soft">
                          {request.intake_source === 'drop'
                            ? '—'
                            : (request.display_label ?? '—')}
                        </td>
                      ) : null}
                      <td>
                        <Link
                          to="/requests/$requestId"
                          params={{ requestId: request.id }}
                          className="relative z-10 font-mono text-xs text-habeas-mid group-hover:text-habeas-navy"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {request.id}
                        </Link>
                      </td>
                      <td className="font-mono text-[0.65rem] text-ink-soft">
                        {request.raw_record_id ?? '—'}
                      </td>
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
              </tbody>
            </table>
          </div>
        )}
      </div>

      <RequestDetailDrawer
        requestId={dialogRequestId}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
      />
    </section>
  )
}
