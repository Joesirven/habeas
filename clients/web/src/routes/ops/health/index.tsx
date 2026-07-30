import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { getDropWorkers, getHealthQueues, type DropWorkerRecord, type HealthQueueRecord } from '@/lib/api'
import { RoleGate, isSuperAdmin } from '@/lib/auth'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function WorkersTable({ workers }: { workers: DropWorkerRecord[] }) {
  if (workers.length === 0) {
    return <p className="text-sm text-ink-soft">No workers reported.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="taste-table">
        <thead>
          <tr>
            <th>Worker</th>
            <th>Health</th>
            <th>Ready</th>
            <th>Pending</th>
            <th>In flight</th>
            <th>Failed terminal</th>
            <th>Oldest pending (s)</th>
          </tr>
        </thead>
        <tbody>
          {workers.map((worker) => (
            <tr key={worker.name}>
              <td className="font-mono text-xs">{worker.name}</td>
              <td>
                <span className={worker.ok ? 'text-emerald-700' : 'text-red-700'}>
                  {worker.ok ? 'up' : 'down'}
                </span>
              </td>
              <td className="font-mono text-xs text-ink-soft">{worker.ready.status ?? '—'}</td>
              <td className="tabular-nums">{worker.queue.pending}</td>
              <td className="tabular-nums">{worker.queue.in_flight}</td>
              <td className="tabular-nums">{worker.queue.failed_terminal}</td>
              <td className="tabular-nums text-ink-soft">
                {worker.queue.oldest_pending_age_seconds ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function QueuesRollup({ queues }: { queues: HealthQueueRecord[] }) {
  if (queues.length === 0) {
    return <p className="text-sm text-ink-soft">No queue tables configured.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="taste-table">
        <thead>
          <tr>
            <th>Worker</th>
            <th>Table</th>
            <th>Pending</th>
            <th>Claimed</th>
            <th>In flight</th>
            <th>Failed terminal</th>
            <th>By status</th>
            <th>Oldest pending (s)</th>
          </tr>
        </thead>
        <tbody>
          {queues.map((queue) => (
            <tr key={`${queue.worker}-${queue.table ?? 'none'}`}>
              <td className="font-mono text-xs">{queue.worker}</td>
              <td className="font-mono text-xs text-ink-soft">{queue.table ?? '—'}</td>
              <td className="tabular-nums">{queue.pending}</td>
              <td className="tabular-nums">{queue.claimed}</td>
              <td className="tabular-nums">{queue.in_flight}</td>
              <td className="tabular-nums">{queue.failed_terminal}</td>
              <td className="max-w-[18rem] text-[0.65rem] text-ink-soft">
                {queue.by_status.length === 0
                  ? '—'
                  : queue.by_status
                      .map((row) => `${row.status}:${row.count}`)
                      .join(' · ')}
              </td>
              <td className="tabular-nums text-ink-soft">
                {queue.oldest_pending_age_seconds ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function HealthLandingPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <HealthLandingBody />
    </RoleGate>
  )
}

function HealthLandingBody() {
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
  const workersDown = workers.filter((worker) => !worker.ok).length
  const failedTerminal = queues.reduce((sum, queue) => sum + queue.failed_terminal, 0)

  return (
    <section className="space-y-12">
      <header className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
        <div>
          <Micro>Operations</Micro>
          <h2 className="mt-3 max-w-md font-display text-[2.75rem] font-medium leading-[1.05] tracking-tight text-ink sm:text-[3.25rem]">
            Health
          </h2>
        </div>
        <p className="max-w-sm border-l border-line pl-5 text-sm leading-relaxed text-ink-soft">
          Worker readiness and queue depths across the DROP spine — including reaper,
          intake poller, and communication attempt tables. Counts and ids only — no
          personally identifiable information.
        </p>
      </header>

      <div className="taste-panel-soft p-6 sm:p-7">
        <Micro>Summary</Micro>
        <div className="mt-4 overflow-x-auto">
          <table className="taste-table">
            <tbody>
              <tr>
                <td className="!px-0 text-ink-soft">Workers down</td>
                <td className="!px-0 tabular-nums">{workersQuery.isSuccess ? workersDown : '—'}</td>
              </tr>
              <tr>
                <td className="!px-0 text-ink-soft">Failed terminal (all queues)</td>
                <td className="!px-0 tabular-nums">
                  {queuesQuery.isSuccess ? failedTerminal : '—'}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link to="/ops/health/escalations" className="taste-btn text-xs">
            Escalations / retries →
          </Link>
          <Link to="/ops/health/configuration" className="taste-btn text-xs">
            Configuration →
          </Link>
        </div>
      </div>

      <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
        <div>
          <Micro>Workers</Micro>
          <p className="mt-2 text-sm text-ink-soft">
            Readiness probes and per-worker queue snapshot from admin-api.
          </p>
        </div>
        {workersQuery.isPending && !workersQuery.data ? (
          <SkeletonLines lines={5} />
        ) : null}
        {workersQuery.isError && !workersQuery.data ? (
          <p className="text-sm text-red-700">Could not load worker health.</p>
        ) : null}
        {workersQuery.data ? <WorkersTable workers={workers} /> : null}
      </div>

      <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
        <div>
          <Micro>Queues rollup</Micro>
          <p className="mt-2 text-sm text-ink-soft">
            Global attempt-table depths aggregated for Health monitoring.
          </p>
        </div>
        {queuesQuery.isPending && !queuesQuery.data ? (
          <SkeletonLines lines={4} />
        ) : null}
        {queuesQuery.isError && !queuesQuery.data ? (
          <p className="text-sm text-red-700">Could not load queue rollup.</p>
        ) : null}
        {queuesQuery.data ? <QueuesRollup queues={queues} /> : null}
      </div>
    </section>
  )
}
