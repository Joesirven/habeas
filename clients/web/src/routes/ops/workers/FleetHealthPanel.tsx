import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useMemo, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { actionToast } from '@/lib/action-toast'
import { getFleetWorkers, type FleetWorkerRecord } from '@/lib/api'
import {
  fleetHealthOk,
  fleetWorkerDisplayName,
  orderedWorkers,
  workerKey,
} from '@/lib/worker-fleet'

type FleetHealthSearch = {
  health?: 'ok' | 'down'
  worker?: string
  table?: string
}

const HEALTH_FILTERS = [
  { value: undefined, label: 'All' },
  { value: 'ok' as const, label: 'ok' },
  { value: 'down' as const, label: 'down' },
]

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function parseFleetHealthSearch(
  search: Record<string, unknown>,
): FleetHealthSearch {
  const parsed: FleetHealthSearch = {}
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

function includesNormalized(
  haystack: string | null | undefined,
  needle: string,
): boolean {
  if (!needle) return true
  return (haystack ?? '').toLowerCase().includes(needle.toLowerCase())
}

function workerMatchesFilters(
  worker: FleetWorkerRecord,
  filters: FleetHealthSearch,
): boolean {
  if (filters.health) {
    const ok = fleetHealthOk(worker)
    if (filters.health === 'ok' && ok !== true) return false
    if (filters.health === 'down' && ok !== false) return false
  }
  if (filters.worker && !includesNormalized(workerKey(worker), filters.worker)) {
    return false
  }
  if (filters.table && !includesNormalized(worker.attempt_table, filters.table)) {
    return false
  }
  return true
}

function flagChip(on: boolean, labelOn: string, labelOff: string) {
  return (
    <span
      className={
        on
          ? 'taste-frost-chip border-emerald-200/80 text-emerald-800'
          : 'taste-frost-chip text-mute'
      }
    >
      {on ? labelOn : labelOff}
    </span>
  )
}

export function FleetHealthPanel() {
  const navigate = useNavigate()
  const search = parseFleetHealthSearch(
    useSearch({ strict: false }) as Record<string, unknown>,
  )

  const fleetQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fleet-workers'],
    queryFn: getFleetWorkers,
    refetchInterval: 20_000,
    placeholderData: (previous) => previous,
  })

  const workers = orderedWorkers(fleetQuery.data)
  const visibleWorkers = useMemo(
    () => workers.filter((worker) => workerMatchesFilters(worker, search)),
    [workers, search.health, search.worker, search.table],
  )
  const warnings = fleetQuery.data?.discovery_warnings ?? []
  const mode = fleetQuery.data?.discovery_mode
  const filtersActive = Boolean(search.health || search.worker || search.table)

  function patchSearch(patch: Partial<FleetHealthSearch>) {
    const next: FleetHealthSearch = {
      health: 'health' in patch ? patch.health : search.health,
      worker: 'worker' in patch ? patch.worker : search.worker,
      table: 'table' in patch ? patch.table : search.table,
    }
    void navigate({
      to: '/ops/workers/settings',
      search: next as never,
      replace: true,
    })
  }

  return (
    <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Fleet health</Micro>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            Ready probes from discovery
            {mode ? (
              <>
                {' '}
                · <span className="font-mono text-xs">{mode}</span>
              </>
            ) : null}
            . Poll ~20s.
          </p>
        </div>
        {fleetQuery.isFetching && fleetQuery.data ? (
          <span className="taste-frost-chip">Refreshing</span>
        ) : null}
      </div>

      <div className="flex flex-wrap items-end gap-2 rounded-md border border-line bg-paper/60 px-3 py-2">
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
            list="fleet-worker-keys"
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
            list="fleet-attempt-tables"
          />
        </label>
        {filtersActive ? (
          <button
            type="button"
            className="taste-btn text-xs"
            onClick={() =>
              patchSearch({ health: undefined, worker: undefined, table: undefined })
            }
          >
            Clear
          </button>
        ) : null}
        {fleetQuery.data && workers.length > 0 ? (
          <span className="ml-auto text-[0.65rem] text-mute tabular-nums">
            {visibleWorkers.length}
            {filtersActive ? ` / ${workers.length}` : ''} workers
          </span>
        ) : null}
        <datalist id="fleet-worker-keys">
          {workers.map((worker) => {
            const key = workerKey(worker)
            return key ? <option key={key} value={key} /> : null
          })}
        </datalist>
        <datalist id="fleet-attempt-tables">
          {workers.map((worker) =>
            worker.attempt_table ? (
              <option key={worker.attempt_table} value={worker.attempt_table} />
            ) : null,
          )}
        </datalist>
      </div>

      {fleetQuery.isPending && !fleetQuery.data ? <SkeletonLines lines={5} /> : null}

      {fleetQuery.isError && !fleetQuery.data ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-red-700">Could not load fleet discovery.</p>
          <button
            type="button"
            className="taste-btn px-2.5 py-1 text-[0.65rem]"
            onClick={() => {
              void fleetQuery.refetch().catch((error) => {
                actionToast.error({
                  title: 'Fleet refresh failed',
                  description: actionToast.safeErrorMessage(error),
                  action: {
                    label: 'Retry',
                    onClick: () => void fleetQuery.refetch(),
                  },
                })
              })
            }}
          >
            Retry
          </button>
        </div>
      ) : null}

      {warnings.length > 0 ? (
        <ul className="space-y-1 text-xs text-ink-soft">
          {warnings.map((w, index) => (
            <li key={`${w.code ?? 'warn'}:${w.detail ?? index}`}>
              <span className="font-mono text-mute">{w.code ?? 'warning'}</span>
              {w.detail ? ` — ${w.detail}` : null}
            </li>
          ))}
        </ul>
      ) : null}

      {fleetQuery.data ? (
        workers.length === 0 ? (
          <p className="text-sm text-ink-soft">
            No workers discovered yet. They appear when Scheduler or Cloud Run discovery finds them.
          </p>
        ) : visibleWorkers.length === 0 ? (
          <p className="text-sm text-ink-soft">
            No workers match the current filters.{' '}
            <button
              type="button"
              className="underline"
              onClick={() =>
                patchSearch({ health: undefined, worker: undefined, table: undefined })
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
                  <th>Worker</th>
                  <th>Ready</th>
                  <th>Flags</th>
                  <th>Service</th>
                  <th>Queue table</th>
                </tr>
              </thead>
              <tbody>
                {visibleWorkers.map((worker) => {
                  const key = workerKey(worker)
                  const ok = fleetHealthOk(worker)
                  const statusCode = worker.health?.status_code ?? worker.status_code
                  return (
                    <tr key={key}>
                      <td>
                        <p className="text-sm text-ink">{fleetWorkerDisplayName(worker)}</p>
                        <p className="font-mono text-[0.65rem] text-mute">{key}</p>
                      </td>
                      <td>
                        {ok == null ? (
                          <span className="taste-frost-chip text-mute">unknown</span>
                        ) : (
                          <span
                            className={
                              ok
                                ? 'taste-status-ok inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[0.65rem]'
                                : 'taste-status-fail inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[0.65rem]'
                            }
                          >
                            <span className="taste-status-dot h-1.5 w-1.5 rounded-full" />
                            {ok ? 'ok' : 'fail'}
                            {statusCode != null ? (
                              <span className="tabular-nums text-mute">{statusCode}</span>
                            ) : null}
                          </span>
                        )}
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-1">
                          {flagChip(worker.deployed, 'deployed', 'not deployed')}
                          {flagChip(worker.scheduled, 'scheduled', 'unscheduled')}
                        </div>
                      </td>
                      <td className="font-mono text-xs text-ink-soft">
                        {worker.service_name ?? '—'}
                      </td>
                      <td>
                        {worker.attempt_table ? (
                          <Link
                            to="/ops/workers/$workerName/queue"
                            params={{ workerName: key }}
                            className="font-mono text-xs text-habeas-mid underline decoration-habeas-mid/30 underline-offset-2"
                          >
                            {worker.attempt_table}
                          </Link>
                        ) : (
                          <span className="text-xs text-mute">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )
      ) : null}
    </div>
  )
}
