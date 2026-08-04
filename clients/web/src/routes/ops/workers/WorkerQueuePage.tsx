import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { type FormEvent, type ReactNode, useMemo, useState } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  getAttemptTableCatalog,
  getAttemptTableRows,
  getFleetWorkers,
} from '@/lib/api'
import { RoleGate, isSuperAdmin } from '@/lib/auth'
import {
  attemptTableForWorker,
  resolveAttemptColumns,
  supportsUnifiedRuns,
  workerByName,
  workerDisplayLabel,
  workerKey,
} from '@/lib/worker-fleet'
import {
  runsSearchForWorker,
  type WorkerQueueSearch,
  type WorkerQueueWindow,
} from '@/router'

const WINDOW_OPTIONS: { value: WorkerQueueWindow; label: string }[] = [
  { value: '8h', label: '8h' },
  { value: '1w', label: '1w' },
  { value: '3m', label: '3m' },
  { value: 'custom', label: 'custom' },
]

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'pending', label: 'pending' },
  { value: 'claimed', label: 'claimed' },
  { value: 'in_flight', label: 'in_flight' },
  { value: 'success', label: 'success' },
  { value: 'failed', label: 'failed' },
  { value: 'failed_terminal', label: 'failed_terminal' },
  { value: 'abandoned', label: 'abandoned' },
] as const

const DEFAULT_LIMIT = 50

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function cellValue(value: string | number | boolean | null | undefined): string {
  if (value == null) return '—'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}

function WorkerQueueBody() {
  const navigate = useNavigate()
  const { workerName } = useParams({ from: '/ops/workers/$workerName/queue' })
  const search = useSearch({ from: '/ops/workers/$workerName/queue' })

  const fleetQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fleet-workers'],
    queryFn: getFleetWorkers,
    refetchInterval: 30_000,
  })

  const catalogQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'attempt-tables'],
    queryFn: getAttemptTableCatalog,
    refetchInterval: 30_000,
  })

  const worker = workerByName(fleetQuery.data, workerName)
  const workerTables = useMemo(() => {
    const fromCatalog = (catalogQuery.data?.tables ?? []).filter(
      (entry) => (entry.worker_key ?? entry.worker_name) === workerName,
    )
    const conventional = attemptTableForWorker(fleetQuery.data, workerName)
    if (
      conventional &&
      !fromCatalog.some((entry) => entry.table_name === conventional)
    ) {
      return [
        ...fromCatalog,
        {
          table_name: conventional,
          worker_key: workerName,
          worker_name: workerName,
        },
      ]
    }
    return fromCatalog
  }, [catalogQuery.data?.tables, fleetQuery.data, workerName])

  const ownedTableNames = new Set(workerTables.map((entry) => entry.table_name))
  const preferredTable =
    attemptTableForWorker(fleetQuery.data, workerName) ??
    workerTables[0]?.table_name
  const discoveredTable =
    search.table && ownedTableNames.has(search.table)
      ? search.table
      : preferredTable

  const tableName = discoveredTable ?? undefined
  const window = search.window ?? '1w'
  const limit = search.limit ?? DEFAULT_LIMIT
  const offset = search.offset ?? 0

  const [draftRequestId, setDraftRequestId] = useState(search.request_id ?? '')
  const [draftStep, setDraftStep] = useState(search.step ?? '')
  const [draftSince, setDraftSince] = useState(
    search.since ? search.since.slice(0, 16) : '',
  )

  const rowsQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'attempt-table-rows',
      tableName,
      search.status,
      search.request_id,
      search.step,
      window,
      search.since,
      limit,
      offset,
    ],
    queryFn: () =>
      getAttemptTableRows({
        table_name: tableName!,
        status: search.status,
        request_id: search.request_id,
        step: search.step,
        window: window === 'custom' ? 'custom' : window,
        since: search.since,
        limit,
        offset,
      }),
    enabled: Boolean(tableName),
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const catalogEntry = catalogQuery.data?.tables.find(
    (entry) => entry.table_name === tableName,
  )

  const columns = useMemo(() => {
    if (rowsQuery.data?.columns?.length) return rowsQuery.data.columns
    if (catalogEntry) return resolveAttemptColumns(catalogEntry)
    return []
  }, [rowsQuery.data?.columns, catalogEntry])

  const rows = rowsQuery.data?.rows ?? []
  const rowCount = rowsQuery.data?.total ?? rowsQuery.data?.count ?? rows.length
  const refreshedAt = rowsQuery.dataUpdatedAt
    ? new Date(rowsQuery.dataUpdatedAt).toLocaleTimeString()
    : '—'

  function patchSearch(patch: Partial<WorkerQueueSearch>) {
    void navigate({
      to: '/ops/workers/$workerName/queue',
      params: { workerName },
      search: {
        table: 'table' in patch ? patch.table : search.table,
        status: 'status' in patch ? patch.status : search.status,
        window: 'window' in patch ? patch.window : search.window,
        since: 'since' in patch ? patch.since : search.since,
        request_id: 'request_id' in patch ? patch.request_id : search.request_id,
        step: 'step' in patch ? patch.step : search.step,
        limit: 'limit' in patch ? patch.limit : search.limit,
        offset: 'offset' in patch ? patch.offset : search.offset,
      },
      replace: true,
    })
  }

  function applyFilters(event: FormEvent) {
    event.preventDefault()
    patchSearch({
      request_id: draftRequestId.trim() || undefined,
      step: draftStep.trim() || undefined,
      since:
        window === 'custom' && draftSince
          ? new Date(draftSince).toISOString()
          : window === 'custom'
            ? undefined
            : undefined,
      offset: 0,
    })
  }

  function clearFilters() {
    setDraftRequestId('')
    setDraftStep('')
    setDraftSince('')
    patchSearch({
      status: undefined,
      window: '1w',
      since: undefined,
      request_id: undefined,
      step: undefined,
      limit: DEFAULT_LIMIT,
      offset: 0,
    })
  }

  const fleetLoading = fleetQuery.isPending && !fleetQuery.data
  const showEmptyNoTable =
    !fleetLoading && !catalogQuery.isPending && !tableName

  return (
    <section className="taste-ops-page space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Workers · Queue</Micro>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              {worker ? workerDisplayLabel(worker) : workerName}
            </h2>
            {rowsQuery.isFetching && tableName ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-ink-soft">
            Allowlisted attempt rows · poll 15s · refreshed {refreshedAt}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/ops/workers/settings/tables" className="taste-btn text-xs">
            Attempt tables
          </Link>
          <Link to="/ops/workers" className="taste-btn text-xs">
            ← Overview
          </Link>
          {worker && supportsUnifiedRuns(worker) ? (
            <Link
              to="/ops/runs"
              search={runsSearchForWorker(workerKey(worker))}
              className="taste-btn text-xs"
            >
              Runs →
            </Link>
          ) : null}
        </div>
      </header>

      {showEmptyNoTable ? (
        <div className="taste-panel p-5">
          <p className="text-sm text-ink-soft">No queue table for this worker.</p>
          <p className="mt-2 text-xs text-mute">
            Health and schedules may still apply; attempt browser only covers discovered{' '}
            <span className="font-mono">*_attempts</span> tables.
          </p>
          {worker && supportsUnifiedRuns(worker) ? (
            <Link
              to="/ops/runs"
              search={runsSearchForWorker(workerKey(worker))}
              className="taste-link mt-3 inline-block text-xs"
            >
              Open Runs history →
            </Link>
          ) : null}
        </div>
      ) : null}

      {tableName ? (
        <>
          <form
            className="taste-panel flex flex-wrap items-end gap-2 p-3 sm:p-4"
            onSubmit={applyFilters}
          >
            <label className="flex flex-col gap-1 text-xs text-ink-soft">
              Table
              <select
                className="rounded-md border border-line bg-paper px-2 py-1.5 font-mono text-xs text-ink"
                value={tableName}
                onChange={(event) =>
                  patchSearch({ table: event.target.value, offset: 0 })
                }
              >
                {(workerTables.length > 0
                  ? workerTables
                  : tableName
                    ? [{ table_name: tableName }]
                    : []
                ).map((entry) => (
                      <option key={entry.table_name} value={entry.table_name}>
                        {entry.table_name}
                      </option>
                    ))}
              </select>
            </label>

            <label className="flex flex-col gap-1 text-xs text-ink-soft">
              Status
              <select
                className="rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
                value={search.status ?? ''}
                onChange={(event) =>
                  patchSearch({
                    status: event.target.value ? event.target.value : undefined,
                    offset: 0,
                  })
                }
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option.value || 'all'} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <div className="flex flex-col gap-1 text-xs text-ink-soft">
              Window
              <div className="flex gap-1">
                {WINDOW_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className={
                      window === option.value
                        ? 'taste-btn-primary text-xs'
                        : 'taste-btn text-xs'
                    }
                    onClick={() =>
                      patchSearch({
                        window: option.value,
                        since:
                          option.value === 'custom' ? search.since : undefined,
                        offset: 0,
                      })
                    }
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            {window === 'custom' ? (
              <label className="flex flex-col gap-1 text-xs text-ink-soft">
                Since
                <input
                  type="datetime-local"
                  className="rounded-md border border-line bg-paper px-2 py-1 font-mono text-xs"
                  value={draftSince}
                  onChange={(event) => setDraftSince(event.target.value)}
                />
              </label>
            ) : null}

            <label className="flex flex-col gap-1 text-xs text-ink-soft">
              Request id
              <input
                type="text"
                className="min-w-[10rem] rounded-md border border-line bg-paper px-2 py-1.5 font-mono text-xs"
                value={draftRequestId}
                onChange={(event) => setDraftRequestId(event.target.value)}
                placeholder="uuid"
                autoComplete="off"
              />
            </label>

            <label className="flex flex-col gap-1 text-xs text-ink-soft">
              Step
              <input
                type="text"
                className="min-w-[7rem] rounded-md border border-line bg-paper px-2 py-1.5 font-mono text-xs"
                value={draftStep}
                onChange={(event) => setDraftStep(event.target.value)}
                placeholder="optional"
                autoComplete="off"
              />
            </label>

            <label className="flex flex-col gap-1 text-xs text-ink-soft">
              Limit
              <select
                className="rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
                value={String(limit)}
                onChange={(event) =>
                  patchSearch({
                    limit: Number.parseInt(event.target.value, 10) || DEFAULT_LIMIT,
                    offset: 0,
                  })
                }
              >
                {[25, 50, 100, 200].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>

            <div className="flex gap-1.5">
              <button type="submit" className="taste-btn-primary text-xs">
                Apply
              </button>
              <button type="button" className="taste-btn text-xs" onClick={clearFilters}>
                Clear
              </button>
            </div>
          </form>

          <div className="taste-panel overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
              <Micro>
                <span className="font-mono">{tableName}</span>
                {' · '}
                <span className="tabular-nums">{rowCount}</span> rows
                {' · '}
                refreshed {refreshedAt}
              </Micro>
              <div className="flex gap-1">
                <button
                  type="button"
                  className="taste-btn text-xs"
                  disabled={offset <= 0}
                  onClick={() =>
                    patchSearch({ offset: Math.max(0, offset - limit) })
                  }
                >
                  ← Prev
                </button>
                <button
                  type="button"
                  className="taste-btn text-xs"
                  disabled={
                    rows.length < limit &&
                    (rowsQuery.data?.next_offset == null ||
                      rowsQuery.data.next_offset < 0)
                  }
                  onClick={() => {
                    const next =
                      rowsQuery.data?.next_offset != null
                        ? rowsQuery.data.next_offset
                        : offset + limit
                    patchSearch({ offset: next })
                  }}
                >
                  Next →
                </button>
              </div>
            </div>

            {rowsQuery.isError ? (
              <p className="px-3 py-4 text-xs text-red-700">
                Could not load rows.{' '}
                <button
                  type="button"
                  className="underline"
                  onClick={() => void rowsQuery.refetch()}
                >
                  Retry
                </button>
              </p>
            ) : rowsQuery.isPending && !rowsQuery.data ? (
              <div className="p-4">
                <SkeletonLines lines={6} />
              </div>
            ) : columns.length === 0 ? (
              <p className="px-3 py-4 text-xs text-ink-soft">
                No allowlisted columns returned for this table.
              </p>
            ) : rows.length === 0 ? (
              <p className="px-3 py-4 text-xs text-ink-soft">
                No rows match the current filters.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="taste-table">
                  <thead>
                    <tr>
                      {columns.map((column) => (
                        <th key={column}>{column}</th>
                      ))}
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => {
                      const id = row.id
                      const runJob =
                        worker && supportsUnifiedRuns(worker)
                          ? workerKey(worker)
                          : null
                      return (
                        <tr key={id != null ? String(id) : `row-${index}`}>
                          {columns.map((column) => (
                            <td
                              key={column}
                              className={
                                column === 'id' ||
                                column === 'request_id' ||
                                column === 'worker_id'
                                  ? 'font-mono text-xs tabular-nums'
                                  : 'text-xs'
                              }
                            >
                              {cellValue(row[column])}
                            </td>
                          ))}
                          <td className="text-right">
                            {runJob && id != null ? (
                              <Link
                                to="/ops/runs/$job/$attemptId"
                                params={{
                                  job: runJob,
                                  attemptId: String(id),
                                }}
                                className="taste-link text-xs"
                              >
                                Run
                              </Link>
                            ) : id != null ? (
                              <span className="font-mono text-[0.65rem] text-mute">
                                #{String(id)}
                              </span>
                            ) : (
                              <span className="text-mute">—</span>
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
        </>
      ) : fleetLoading || catalogQuery.isPending ? (
        <div className="taste-panel-soft p-5">
          <SkeletonLines lines={4} />
        </div>
      ) : null}
    </section>
  )
}

export function WorkerQueuePage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <WorkerQueueBody />
    </RoleGate>
  )
}
