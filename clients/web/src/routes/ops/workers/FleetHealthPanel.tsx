import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { actionToast } from '@/lib/action-toast'
import { getFleetWorkers } from '@/lib/api'
import {
  fleetHealthOk,
  fleetWorkerDisplayName,
  workerKey,
} from '@/lib/worker-fleet'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
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
  const fleetQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fleet-workers'],
    queryFn: getFleetWorkers,
    refetchInterval: 20_000,
    placeholderData: (previous) => previous,
  })

  const workers = fleetQuery.data?.workers ?? []
  const warnings = fleetQuery.data?.discovery_warnings ?? []
  const mode = fleetQuery.data?.discovery_mode

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
                {workers.map((worker) => {
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
