import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useMemo, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { getAttemptTableCatalog, getFleetWorkers } from '@/lib/api'
import { RoleGate, isSuperAdmin } from '@/lib/auth'
import {
  fleetHealthOk,
  orderedWorkers,
  resolveAttemptColumns,
  workerByKey,
  workerKey,
} from '@/lib/worker-fleet'
import type { AttemptTablesSearch } from '@/router'

type TablesFilterSearch = AttemptTablesSearch & {
  health?: 'ok' | 'down'
}

function parseTablesFilterSearch(
  search: Record<string, unknown>,
): TablesFilterSearch {
  const parsed: TablesFilterSearch = {}
  if (search.health === 'ok' || search.health === 'down') {
    parsed.health = search.health
  }
  if (typeof search.worker === 'string' && search.worker.trim()) {
    parsed.worker = search.worker.trim()
  }
  if (typeof search.table === 'string' && search.table.trim()) {
    parsed.table = search.table.trim()
  }
  return parsed
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

const HEALTH_FILTERS = [
  { value: undefined, label: 'All' },
  { value: 'ok' as const, label: 'ok' },
  { value: 'down' as const, label: 'down' },
]

function includesNormalized(
  haystack: string | null | undefined,
  needle: string,
): boolean {
  if (!needle) return true
  return (haystack ?? '').toLowerCase().includes(needle.toLowerCase())
}

function AttemptTablesIndexBody() {
  const navigate = useNavigate()
  const routeSearch = useSearch({ from: '/ops/workers/settings/tables' })
  const looseSearch = parseTablesFilterSearch(
    useSearch({ strict: false }) as Record<string, unknown>,
  )
  const [sessionHealth, setSessionHealth] = useState<TablesFilterSearch['health']>(
    looseSearch.health,
  )
  const search: TablesFilterSearch = {
    table: 'table' in looseSearch ? looseSearch.table : routeSearch.table,
    worker: 'worker' in looseSearch ? looseSearch.worker : routeSearch.worker,
    health: looseSearch.health ?? sessionHealth,
  }

  const catalogQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'attempt-tables'],
    queryFn: getAttemptTableCatalog,
    refetchInterval: 30_000,
  })

  const fleetQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fleet-workers'],
    queryFn: getFleetWorkers,
    refetchInterval: 30_000,
  })

  const tables = catalogQuery.data?.tables ?? []
  const workers = orderedWorkers(fleetQuery.data)
  const catalogKeys = useMemo(() => {
    const keys = new Set<string>()
    for (const worker of workers) {
      const key = workerKey(worker)
      if (key) keys.add(key)
    }
    for (const entry of tables) {
      const key = entry.worker_key ?? entry.worker_name
      if (key) keys.add(key)
    }
    return [...keys]
  }, [tables, workers])
  const catalogTableNames = useMemo(
    () => [...new Set(tables.map((entry) => entry.table_name).filter(Boolean))],
    [tables],
  )

  function patchSearch(patch: Partial<TablesFilterSearch>) {
    if ('health' in patch) setSessionHealth(patch.health)
    const next: TablesFilterSearch = {
      table: 'table' in patch ? patch.table : search.table,
      worker: 'worker' in patch ? patch.worker : search.worker,
      health: 'health' in patch ? patch.health : search.health,
    }
    void navigate({
      to: '/ops/workers/settings/tables',
      search: next as AttemptTablesSearch,
      replace: true,
    })
  }

  const visibleTables = useMemo(() => {
    return tables.filter((entry) => {
      if (
        search.table &&
        !includesNormalized(entry.table_name, search.table)
      ) {
        return false
      }
      const key = entry.worker_key ?? entry.worker_name
      if (search.worker && !includesNormalized(key, search.worker)) {
        return false
      }
      if (search.health) {
        const fleetWorker = key ? workerByKey(fleetQuery.data, key) : undefined
        const ok = fleetWorker ? fleetHealthOk(fleetWorker) : null
        if (search.health === 'ok' && ok !== true) return false
        if (search.health === 'down' && ok !== false) return false
      }
      return true
    })
  }, [tables, search.table, search.worker, search.health, fleetQuery.data])

  const filtersActive = Boolean(search.health || search.worker || search.table)

  const loading =
    (catalogQuery.isPending && !catalogQuery.data) ||
    (fleetQuery.isPending && !fleetQuery.data)

  return (
    <section className="taste-ops-page space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Workers · Settings</Micro>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              Attempt tables
            </h2>
            {(catalogQuery.isFetching || fleetQuery.isFetching) && !loading ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>
          <p className="mt-1 max-w-xl text-xs text-ink-soft">
            Allowlisted queue tables from discovery — structured filters only; no free SQL.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to="/ops/workers/settings"
            search={
              {
                health: search.health,
                worker: search.worker,
                table: search.table,
              } as never
            }
            className="taste-btn text-xs"
          >
            ← Settings
          </Link>
          <Link to="/ops/workers" className="taste-btn text-xs">
            Overview
          </Link>
        </div>
      </header>

      <div className="taste-panel overflow-hidden">
        <div className="flex flex-wrap items-end justify-between gap-2 border-b border-line px-3 py-2">
          <Micro>Catalog</Micro>
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex flex-col gap-1 text-xs text-ink-soft">
              Health
              <div className="flex gap-1">
                {HEALTH_FILTERS.map((option) => {
                  const active = search.health === option.value
                  return (
                    <button
                      key={option.label}
                      type="button"
                      className={active ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
                      onClick={() => patchSearch({ health: option.value })}
                    >
                      {option.label}
                    </button>
                  )
                })}
              </div>
            </div>
            <label className="flex flex-col gap-1 text-xs text-ink-soft">
              Worker key
              <input
                type="search"
                className="min-w-[10rem] rounded-md border border-line bg-paper px-2 py-1.5 font-mono text-xs text-ink"
                value={search.worker ?? ''}
                onChange={(event) =>
                  patchSearch({
                    worker: event.target.value.trim() || undefined,
                  })
                }
                placeholder="search key"
                autoComplete="off"
                list="attempt-table-worker-keys"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-soft">
              Attempt table
              <input
                type="search"
                className="min-w-[10rem] rounded-md border border-line bg-paper px-2 py-1.5 font-mono text-xs text-ink"
                value={search.table ?? ''}
                onChange={(event) =>
                  patchSearch({
                    table: event.target.value.trim() || undefined,
                  })
                }
                placeholder="table name"
                autoComplete="off"
                list="attempt-table-names"
              />
            </label>
            {filtersActive ? (
              <button
                type="button"
                className="taste-btn text-xs"
                onClick={() =>
                  patchSearch({
                    health: undefined,
                    worker: undefined,
                    table: undefined,
                  })
                }
              >
                Clear
              </button>
            ) : null}
            <datalist id="attempt-table-worker-keys">
              {catalogKeys.map((key) => (
                <option key={key} value={key} />
              ))}
            </datalist>
            <datalist id="attempt-table-names">
              {catalogTableNames.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </div>
        </div>

        {catalogQuery.isError ? (
          <p className="px-3 py-4 text-xs text-red-700">
            Attempt-table catalog unavailable (API may not be deployed yet).{' '}
            <button
              type="button"
              className="underline"
              onClick={() => void catalogQuery.refetch()}
            >
              Retry
            </button>
          </p>
        ) : loading ? (
          <div className="p-4">
            <SkeletonLines lines={5} />
          </div>
        ) : tables.length === 0 ? (
          <p className="px-3 py-4 text-xs text-ink-soft">
            No allowlisted attempt tables discovered.
          </p>
        ) : visibleTables.length === 0 ? (
          <p className="px-3 py-4 text-xs text-ink-soft">
            No tables match the current filters.{' '}
            <button
              type="button"
              className="underline"
              onClick={() =>
                patchSearch({
                  health: undefined,
                  worker: undefined,
                  table: undefined,
                })
              }
            >
              Clear
            </button>
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="taste-table">
              <thead>
                <tr>
                  <th>Table</th>
                  <th>Worker</th>
                  <th>Columns</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visibleTables
                  .map((entry) => {
                    const worker = entry.worker_key ?? entry.worker_name
                    const columns = resolveAttemptColumns(entry)
                    const queueTo =
                      worker != null
                        ? ({
                            to: '/ops/workers/$workerName/queue' as const,
                            params: { workerName: worker },
                            search: { table: entry.table_name },
                          } as const)
                        : null
                    return (
                      <tr key={entry.table_name}>
                        <td className="font-mono text-xs">{entry.table_name}</td>
                        <td className="font-mono text-xs text-ink-soft">
                          {worker ?? '—'}
                        </td>
                        <td className="text-xs text-ink-soft">
                          {columns.length > 0 ? (
                            <span className="tabular-nums">{columns.length}</span>
                          ) : (
                            '—'
                          )}
                        </td>
                        <td className="text-right">
                          {queueTo ? (
                            <Link
                              {...queueTo}
                              className="taste-link text-xs"
                            >
                              Browse →
                            </Link>
                          ) : (
                            <Link
                              to="/ops/workers/settings/tables"
                              search={{ table: entry.table_name }}
                              className="taste-link text-xs"
                              onClick={(event) => {
                                event.preventDefault()
                                patchSearch({ table: entry.table_name })
                              }}
                            >
                              Select
                            </Link>
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

      {search.table && tables.some((entry) => entry.table_name === search.table) ? (
        <p className="text-xs text-ink-soft">
          Selected{' '}
          <span className="font-mono text-ink">{search.table}</span>
          {' · '}
          {(() => {
            const entry = tables.find((t) => t.table_name === search.table)
            const worker = entry?.worker_key ?? entry?.worker_name ?? search.worker
            if (!worker) return 'open a worker queue when mapping exists'
            return (
              <Link
                to="/ops/workers/$workerName/queue"
                params={{ workerName: worker }}
                search={{ table: search.table }}
                className="taste-link"
              >
                Open queue browser →
              </Link>
            )
          })()}
        </p>
      ) : null}
    </section>
  )
}

export function AttemptTablesIndexPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <AttemptTablesIndexBody />
    </RoleGate>
  )
}
