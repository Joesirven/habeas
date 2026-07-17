import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  getDropPipeline,
  listRuns,
  type OpsTimeWindow,
  type RunSummary,
  type WorkerHealthProbe,
} from '@/lib/api'
import { RoleGate } from '@/lib/auth'

const WINDOW_OPTIONS: { value: OpsTimeWindow; label: string }[] = [
  { value: '8h', label: '8h' },
  { value: '24h', label: '24h' },
  { value: '1w', label: '1w' },
]

const WORKER_ORDER = [
  'drop_connector',
  'drop_ingestor',
  'request_dispatcher',
  'matching',
  'data_fulfillment',
  'hash_index_refresh',
] as const

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function isFailedStatus(status: string): boolean {
  const normalized = status.toLowerCase()
  return (
    normalized.includes('fail') ||
    normalized.includes('error') ||
    normalized === 'failed_terminal' ||
    normalized === 'abandoned' ||
    normalized === 'timeout'
  )
}

function isInFlightStatus(status: string): boolean {
  const normalized = status.toLowerCase()
  return (
    normalized.includes('claimed') ||
    normalized === 'running' ||
    normalized === 'in_flight' ||
    normalized.includes('pending')
  )
}

function summarizeRuns(runs: RunSummary[]) {
  let failed = 0
  let inFlight = 0
  for (const run of runs) {
    if (isFailedStatus(run.status)) failed += 1
    else if (isInFlightStatus(run.status)) inFlight += 1
  }
  return { total: runs.length, failed, inFlight }
}

function WorkerHealthCard({ probe }: { probe: WorkerHealthProbe }) {
  return (
    <div className="taste-panel-soft px-4 py-3">
      <p className="taste-micro">{probe.name.replaceAll('_', ' ')}</p>
      <p className={`mt-2 text-sm font-medium ${probe.ok ? 'text-emerald-700' : 'text-red-700'}`}>
        {probe.ok ? 'Up' : 'Down'}
      </p>
      <p className="mt-1 font-mono text-[0.65rem] text-mute">
        {probe.status_code ?? '—'} · {probe.ready?.status ?? '—'}
      </p>
    </div>
  )
}

function WindowSelector({
  window,
  onChange,
}: {
  window: OpsTimeWindow
  onChange: (value: OpsTimeWindow) => void
}) {
  return (
    <div className="flex gap-1">
      {WINDOW_OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          className={window === option.value ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function DashboardContent() {
  const [window, setWindow] = useState<OpsTimeWindow>('24h')

  const runsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'runs', 'dashboard', window],
    queryFn: () => listRuns({ window, limit: 200 }),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const pipelineQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-pipeline'],
    queryFn: getDropPipeline,
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const summary = useMemo(() => summarizeRuns(runsQuery.data ?? []), [runsQuery.data])
  const failedRuns = useMemo(
    () => (runsQuery.data ?? []).filter((run) => isFailedStatus(run.status)),
    [runsQuery.data],
  )
  const workersUp = pipelineQuery.data
    ? WORKER_ORDER.filter((name) => pipelineQuery.data!.worker_health[name]?.ok).length
    : null

  const loading =
    (runsQuery.isPending && !runsQuery.data) || (pipelineQuery.isPending && !pipelineQuery.data)

  return (
    <section className="space-y-10">
      <header className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
        <div>
          <Micro>Ops</Micro>
          <div className="mt-3 flex flex-wrap items-baseline gap-3">
            <h2 className="font-display text-[2.5rem] font-medium leading-none tracking-tight text-ink">
              Ops dashboard
            </h2>
            {(runsQuery.isFetching || pipelineQuery.isFetching) && !loading ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>
          <p className="mt-3 max-w-md text-sm text-ink-soft">
            Prefect-style overview — run volume, failed escalation, and worker pools.
          </p>
        </div>
        <WindowSelector window={window} onChange={setWindow} />
      </header>

      {loading ? (
        <div className="taste-panel-soft p-6">
          <SkeletonLines lines={6} />
        </div>
      ) : null}

      {!loading ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="taste-panel-soft px-5 py-4">
              <Micro>Runs ({window})</Micro>
              <p className="mt-2 font-display text-4xl font-medium tabular-nums text-ink">
                {summary.total}
              </p>
            </div>
            <div className="taste-panel-soft px-5 py-4">
              <Micro>Failed</Micro>
              <p className="mt-2 font-display text-4xl font-medium tabular-nums text-red-700">
                {summary.failed}
              </p>
            </div>
            <div className="taste-panel-soft px-5 py-4">
              <Micro>In flight</Micro>
              <p className="mt-2 font-display text-4xl font-medium tabular-nums text-habeas-mid">
                {summary.inFlight}
              </p>
            </div>
            <div className="taste-panel-soft px-5 py-4">
              <Micro>Workers up</Micro>
              <p className="mt-2 font-display text-4xl font-medium tabular-nums text-ink">
                {workersUp != null ? `${workersUp}/${WORKER_ORDER.length}` : '—'}
              </p>
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <Micro>Failed escalation</Micro>
                  <p className="mt-2 text-sm text-ink-soft">
                    Terminal failures in the selected window — open run detail to investigate.
                  </p>
                </div>
                <Link to="/ops/runs" className="taste-btn text-xs">
                  All runs →
                </Link>
              </div>
              {failedRuns.length === 0 ? (
                <p className="text-sm text-ink-soft">No failed runs in this window.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="taste-table">
                    <thead>
                      <tr>
                        <th>Job</th>
                        <th>Status</th>
                        <th>When</th>
                      </tr>
                    </thead>
                    <tbody>
                      {failedRuns.slice(0, 8).map((run) => {
                        const attemptId = run.run_id.split(':').pop() ?? String(run.attempt_number)
                        return (
                          <tr key={run.run_id}>
                            <td className="font-mono text-xs">{run.job}</td>
                            <td className="text-xs text-red-700">{run.status}</td>
                            <td>
                              <Link
                                to="/ops/runs/$job/$attemptId"
                                params={{ job: run.job, attemptId }}
                                className="taste-link text-xs tabular-nums"
                              >
                                {new Date(run.started_at).toLocaleString()}
                              </Link>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
              <div>
                <Micro>Pipeline signals</Micro>
                <p className="mt-2 text-sm text-ink-soft">
                  Live counts from DROP pipeline aggregate — complements run volume above.
                </p>
              </div>
              {pipelineQuery.data ? (
                <dl className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-lg border border-line bg-paper/60 px-4 py-3">
                    <dt className="taste-micro">DROP requests</dt>
                    <dd className="mt-1 text-2xl font-medium tabular-nums">
                      {pipelineQuery.data.drop_requests.count}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-line bg-paper/60 px-4 py-3">
                    <dt className="taste-micro">Review pending</dt>
                    <dd className="mt-1 text-2xl font-medium tabular-nums">
                      {pipelineQuery.data.matching_review.pending}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-line bg-paper/60 px-4 py-3">
                    <dt className="taste-micro">Match success</dt>
                    <dd className="mt-1 text-2xl font-medium tabular-nums">
                      {pipelineQuery.data.matching_attempts.success}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-line bg-paper/60 px-4 py-3">
                    <dt className="taste-micro">Needs attention</dt>
                    <dd className="mt-1">
                      <Link to="/requests/needs-attention" className="taste-link text-sm">
                        Open queue →
                      </Link>
                    </dd>
                  </div>
                </dl>
              ) : pipelineQuery.isError ? (
                <p className="text-sm text-red-700">Could not load pipeline stats.</p>
              ) : null}
            </div>
          </div>

          {pipelineQuery.data ? (
            <div className="space-y-3">
              <Micro>Worker health</Micro>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {WORKER_ORDER.map((name) => {
                  const probe = pipelineQuery.data!.worker_health[name]
                  if (!probe) {
                    return (
                      <div key={name} className="taste-panel-soft px-4 py-3">
                        <p className="taste-micro">{name.replaceAll('_', ' ')}</p>
                        <p className="mt-2 text-sm text-mute">—</p>
                      </div>
                    )
                  }
                  return <WorkerHealthCard key={name} probe={probe} />
                })}
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  )
}

export function OpsDashboardPage() {
  return (
    <RoleGate allow={(role) => role === 'super_admin'}>
      <DashboardContent />
    </RoleGate>
  )
}
