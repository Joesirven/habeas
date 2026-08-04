import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { getDropWorkers, getHealthQueues } from '@/lib/api'
import { RoleGate, isSuperAdmin } from '@/lib/auth'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

export function HealthEscalationsPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <HealthEscalationsBody />
    </RoleGate>
  )
}

function HealthEscalationsBody() {
  const workersQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-workers'],
    queryFn: getDropWorkers,
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const queuesQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'health-queues'],
    queryFn: getHealthQueues,
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const workers = workersQuery.data?.workers ?? []
  const queues = queuesQuery.data?.queues ?? []

  const workersDown = workers.filter((worker) => !worker.ok)
  const queueEscalations = queues.filter(
    (queue) => queue.failed_terminal > 0 || queue.pending > 0 || !workers.find((w) => w.name === queue.worker)?.ok,
  )
  const failedTerminalQueues = queues.filter((queue) => queue.failed_terminal > 0)

  const loading = (workersQuery.isPending && !workersQuery.data) || (queuesQuery.isPending && !queuesQuery.data)
  const error =
    (workersQuery.isError && !workersQuery.data) || (queuesQuery.isError && !queuesQuery.data)

  return (
    <section className="taste-ops-page space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Workers</Micro>
          <h2 className="mt-1 font-display text-xl font-medium tracking-tight text-ink">
            Escalations
          </h2>
          <p className="mt-1 max-w-xl text-xs text-ink-soft">
            Failed terminal attempts and workers that need attention. Ids and counts only.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/ops/workers" className="taste-btn text-xs">
            ← Overview
          </Link>
          <Link to="/ops/workers/settings" className="taste-btn text-xs">
            Settings
          </Link>
        </div>
      </header>

      {loading ? (
        <div className="taste-panel p-4">
          <SkeletonLines lines={6} />
        </div>
      ) : null}

      {error ? (
        <p className="text-sm text-red-700">Could not load escalation data.</p>
      ) : null}

      {!loading && !error ? (
        <>
          <div className="taste-panel flex flex-col gap-4 p-4 sm:p-5">
            <div>
              <Micro>Workers down</Micro>
              <p className="mt-1 text-xs text-ink-soft">
                Workers failing readiness checks — investigate before retrying work.
              </p>
            </div>
            {workersDown.length === 0 ? (
              <p className="text-sm text-ink-soft">No workers down.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="taste-table">
                  <thead>
                    <tr>
                      <th>Worker</th>
                      <th>Status code</th>
                      <th>Queue pending</th>
                      <th>Failed terminal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {workersDown.map((worker) => (
                      <tr key={worker.name}>
                        <td className="font-mono text-xs">{worker.name}</td>
                        <td className="tabular-nums text-ink-soft">{worker.status_code ?? '—'}</td>
                        <td className="tabular-nums">{worker.queue.pending}</td>
                        <td className="tabular-nums">{worker.queue.failed_terminal}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="taste-panel flex flex-col gap-4 p-4 sm:p-5">
            <div>
              <Micro>Failed terminal</Micro>
              <p className="mt-1 text-xs text-ink-soft">
                Attempt rows in terminal failure statuses (submit_error, outcome_error, timeout,
                abandoned).
              </p>
            </div>
            {failedTerminalQueues.length === 0 ? (
              <p className="text-sm text-ink-soft">No failed terminal rows.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="taste-table">
                  <thead>
                    <tr>
                      <th>Worker</th>
                      <th>Table</th>
                      <th>Count</th>
                      <th>Pending</th>
                    </tr>
                  </thead>
                  <tbody>
                    {failedTerminalQueues.map((queue) => (
                      <tr key={`${queue.worker}-failed`}>
                        <td className="font-mono text-xs">{queue.worker}</td>
                        <td className="font-mono text-xs text-ink-soft">{queue.table}</td>
                        <td className="tabular-nums">{queue.failed_terminal}</td>
                        <td className="tabular-nums">{queue.pending}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="taste-panel flex flex-col gap-4 p-4 sm:p-5">
            <div>
              <Micro>Needs attention</Micro>
              <p className="mt-1 text-xs text-ink-soft">
                Queues with backlog, terminal failures, or an unhealthy worker.
              </p>
            </div>
            {queueEscalations.length === 0 ? (
              <p className="text-sm text-ink-soft">Nothing flagged right now.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="taste-table">
                  <thead>
                    <tr>
                      <th>Worker</th>
                      <th>Table</th>
                      <th>Pending</th>
                      <th>In flight</th>
                      <th>Failed terminal</th>
                      <th>Worker health</th>
                    </tr>
                  </thead>
                  <tbody>
                    {queueEscalations.map((queue) => {
                      const worker = workers.find((item) => item.name === queue.worker)
                      return (
                        <tr key={`${queue.worker}-attention`}>
                          <td className="font-mono text-xs">{queue.worker}</td>
                          <td className="font-mono text-xs text-ink-soft">{queue.table}</td>
                          <td className="tabular-nums">{queue.pending}</td>
                          <td className="tabular-nums">{queue.in_flight}</td>
                          <td className="tabular-nums">{queue.failed_terminal}</td>
                          <td>
                            <span
                              className={
                                worker?.ok === false
                                  ? 'text-red-700'
                                  : worker?.ok
                                    ? 'text-emerald-700'
                                    : 'text-mute'
                              }
                            >
                              {worker?.ok === false ? 'down' : worker?.ok ? 'up' : '—'}
                            </span>
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
      ) : null}
    </section>
  )
}
