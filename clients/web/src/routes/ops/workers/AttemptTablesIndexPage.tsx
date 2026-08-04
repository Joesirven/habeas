import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { getAttemptTableCatalog, getFleetWorkers } from '@/lib/api'
import { RoleGate, isSuperAdmin } from '@/lib/auth'
import { orderedWorkers, resolveAttemptColumns, workerKey } from '@/lib/worker-fleet'
import type { AttemptTablesSearch } from '@/router'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function AttemptTablesIndexBody() {
  const navigate = useNavigate()
  const search = useSearch({ from: '/ops/workers/settings/tables' })

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

  function patchSearch(patch: Partial<AttemptTablesSearch>) {
    void navigate({
      to: '/ops/workers/settings/tables',
      search: {
        table: 'table' in patch ? patch.table : search.table,
        worker: 'worker' in patch ? patch.worker : search.worker,
      },
      replace: true,
    })
  }

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
          <Link to="/ops/workers/settings" className="taste-btn text-xs">
            ← Settings
          </Link>
          <Link to="/ops/workers" className="taste-btn text-xs">
            Overview
          </Link>
        </div>
      </header>

      <div className="taste-panel overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
          <Micro>Catalog</Micro>
          <label className="flex items-center gap-1.5 text-xs text-ink-soft">
            Worker
            <select
              className="rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
              value={search.worker ?? ''}
              onChange={(event) =>
                patchSearch({
                  worker: event.target.value ? event.target.value : undefined,
                })
              }
            >
              <option value="">All</option>
              {workers.map((worker) => {
                const key = workerKey(worker)
                return (
                  <option key={key} value={key}>
                    {key}
                  </option>
                )
              })}
            </select>
          </label>
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
                {tables
                  .filter((entry) => {
                    if (!search.worker) return true
                    const key = entry.worker_key ?? entry.worker_name
                    return key === search.worker
                  })
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

      {search.table ? (
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
