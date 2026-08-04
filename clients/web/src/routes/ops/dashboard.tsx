import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  getDropPipeline,
  getFleetWorkers,
  listRuns,
  type OpsTimeWindow,
  type RunSummary,
  type WorkerHealthProbe,
} from '@/lib/api'
import { RoleGate } from '@/lib/auth'
import {
  isWorkerHealthy,
  orderedWorkers,
  workerDisplayLabel,
  workerKey,
} from '@/lib/worker-fleet'

const WINDOW_OPTIONS: { value: OpsTimeWindow; label: string }[] = [
  { value: '8h', label: '8h' },
  { value: '1w', label: '1w' },
  { value: '3m', label: '3m' },
]

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

type VolumeBucket = {
  label: string
  count: number
}

function windowDurationMs(window: OpsTimeWindow): number {
  if (window === '8h') return 8 * 3_600_000
  if (window === '24h') return 24 * 3_600_000
  if (window === '3m') return 90 * 24 * 3_600_000
  return 7 * 24 * 3_600_000
}

function bucketRunsByTime(runs: RunSummary[], window: OpsTimeWindow): VolumeBucket[] {
  const now = Date.now()
  const durationMs = windowDurationMs(window)
  const bucketCount = window === '3m' ? 12 : window === '1w' ? 7 : window === '24h' ? 12 : 8
  const bucketMs = durationMs / bucketCount
  const windowStart = now - durationMs

  const buckets: VolumeBucket[] = Array.from({ length: bucketCount }, (_, index) => {
    const bucketStart = windowStart + index * bucketMs
    const date = new Date(bucketStart)
    const label =
      window === '1w'
        ? date.toLocaleDateString(undefined, { weekday: 'short' })
        : window === '3m'
          ? date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
          : window === '24h'
            ? date.toLocaleTimeString(undefined, { hour: 'numeric' })
            : date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    return { label, count: 0 }
  })

  for (const run of runs) {
    const startedAt = new Date(run.started_at).getTime()
    if (startedAt < windowStart || startedAt > now) continue
    const index = Math.min(
      bucketCount - 1,
      Math.floor((startedAt - windowStart) / bucketMs),
    )
    buckets[index]!.count += 1
  }

  return buckets
}

function VolumeStrip({ runs, window }: { runs: RunSummary[]; window: OpsTimeWindow }) {
  const buckets = useMemo(() => bucketRunsByTime(runs, window), [runs, window])
  const maxCount = Math.max(1, ...buckets.map((bucket) => bucket.count))

  return (
    <div className="space-y-3">
      <div className="flex items-end gap-1" style={{ height: '5.5rem' }} aria-hidden>
        {buckets.map((bucket, index) => {
          const heightPct = (bucket.count / maxCount) * 100
          return (
            <div key={`${bucket.label}-${index}`} className="flex min-w-0 flex-1 flex-col items-center gap-1">
              <div className="flex w-full flex-1 items-end">
                <div
                  className="w-full min-h-[2px] rounded-t-sm bg-habeas-mid transition-[height] duration-300"
                  style={{ height: `${Math.max(heightPct, bucket.count > 0 ? 6 : 0)}%` }}
                  title={`${bucket.count} runs`}
                />
              </div>
              <span className="truncate text-[0.6rem] leading-none text-mute">{bucket.label}</span>
            </div>
          )
        })}
      </div>
      <p className="text-xs text-ink-soft">
        Run volume by {window === '1w' ? 'day' : 'time bucket'} — client-side from{' '}
        <span className="tabular-nums">{runs.length}</span> runs in window.
      </p>
    </div>
  )
}

function TallyRow({
  summary,
  workersUp,
  workersTotal,
  window,
}: {
  summary: { total: number; failed: number; inFlight: number }
  workersUp: number | null
  workersTotal: number
  window: OpsTimeWindow
}) {
  return (
    <dl className="flex flex-wrap gap-x-5 gap-y-2 border-t border-line pt-4 text-sm">
      <div className="flex items-baseline gap-2">
        <dt className="taste-micro !text-[0.65rem]">Runs</dt>
        <dd className="font-medium tabular-nums text-ink">{summary.total}</dd>
        <span className="text-xs text-mute">({window})</span>
      </div>
      <div className="flex items-baseline gap-2">
        <dt className="taste-micro !text-[0.65rem]">Failed</dt>
        <dd className="font-medium tabular-nums text-red-700">{summary.failed}</dd>
      </div>
      <div className="flex items-baseline gap-2">
        <dt className="taste-micro !text-[0.65rem]">In flight</dt>
        <dd className="font-medium tabular-nums text-habeas-mid">{summary.inFlight}</dd>
      </div>
      <div className="flex items-baseline gap-2">
        <dt className="taste-micro !text-[0.65rem]">Workers up</dt>
        <dd className="font-medium tabular-nums text-ink">
          {workersUp != null && workersTotal > 0
            ? `${workersUp}/${workersTotal}`
            : '—'}
        </dd>
      </div>
    </dl>
  )
}

function WorkerHealthCard({
  name,
  probe,
}: {
  name: string
  probe: WorkerHealthProbe | { ok: boolean; status_code?: number | null; ready?: { status?: string } }
}) {
  return (
    <div className="rounded-lg border border-line bg-paper/60 px-3 py-2.5">
      <p className="taste-micro text-[0.65rem]">{name.replaceAll('_', ' ')}</p>
      <p className={`mt-1 text-xs font-medium ${probe.ok ? 'text-emerald-700' : 'text-red-700'}`}>
        {probe.ok ? 'Up' : 'Down'}
      </p>
      <p className="mt-0.5 font-mono text-[0.6rem] text-mute">
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
  const [window, setWindow] = useState<OpsTimeWindow>('1w')

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

  const fleetQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fleet-workers'],
    queryFn: getFleetWorkers,
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const runs = runsQuery.data ?? []
  const summary = useMemo(() => summarizeRuns(runs), [runs])
  const failedRuns = useMemo(() => runs.filter((run) => isFailedStatus(run.status)), [runs])

  const fleetWorkers = orderedWorkers(fleetQuery.data)
  const pipelineHealth = pipelineQuery.data?.worker_health

  /** Prefer fleet discovery order; fall back to pipeline worker_health keys. */
  const workerEntries = useMemo(() => {
    if (fleetWorkers.length > 0) {
      return fleetWorkers.map((worker) => {
        const key = workerKey(worker)
        const probe = pipelineHealth?.[key]
        return {
          name: key,
          label: workerDisplayLabel(worker),
          ok: probe?.ok ?? isWorkerHealthy(worker),
          status_code: probe?.status_code ?? worker.health?.status_code ?? worker.status_code ?? null,
          ready: probe?.ready ?? worker.health?.ready ?? worker.ready,
        }
      })
    }
    if (pipelineHealth) {
      return Object.keys(pipelineHealth).map((name) => {
        const probe = pipelineHealth[name]!
        return {
          name,
          label: name.replaceAll('_', ' '),
          ok: probe.ok,
          status_code: probe.status_code ?? null,
          ready: probe.ready,
        }
      })
    }
    return []
  }, [fleetWorkers, pipelineHealth])

  const workersUp =
    workerEntries.length > 0
      ? workerEntries.filter((entry) => entry.ok).length
      : null

  const loading =
    (runsQuery.isPending && !runsQuery.data) ||
    ((pipelineQuery.isPending && !pipelineQuery.data) &&
      (fleetQuery.isPending && !fleetQuery.data))

  const failedRunsSearch = { status: 'failed' as const, window }

  return (
    <section className="taste-ops-page">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Ops</Micro>
          <div className="flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              Ops dashboard
            </h2>
            {(runsQuery.isFetching ||
              pipelineQuery.isFetching ||
              fleetQuery.isFetching) &&
            !loading ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>
        </div>
        <WindowSelector window={window} onChange={setWindow} />
      </header>

      {loading ? (
        <div className="taste-panel-soft p-5">
          <SkeletonLines lines={6} />
        </div>
      ) : null}

      {!loading ? (
        <>
          <div className="taste-panel-soft p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Micro>Run volume</Micro>
              <Link
                to="/ops/runs"
                search={{ window }}
                className="taste-btn text-xs"
              >
                All runs →
              </Link>
            </div>
            <div className="mt-4">
              <VolumeStrip runs={runs} window={window} />
            </div>
            <TallyRow
              summary={summary}
              workersUp={workersUp}
              workersTotal={workerEntries.length}
              window={window}
            />
          </div>

          <div className="grid gap-5 lg:grid-cols-[1.35fr_0.65fr]">
            <div className="taste-panel-soft flex flex-col gap-4 p-5 sm:p-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <Micro>Failed escalation</Micro>
                  <p className="mt-1 text-xs text-ink-soft">
                    Terminal failures in the selected window.
                  </p>
                </div>
                <Link
                  to="/ops/runs"
                  search={failedRunsSearch}
                  className="taste-btn text-xs"
                >
                  Failed runs →
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

            <div className="taste-panel-soft flex flex-col gap-4 p-5 sm:p-6">
              <div>
                <Micro>Worker pool</Micro>
                <p className="mt-1 text-xs text-ink-soft">Live health probes per worker.</p>
              </div>
              {workerEntries.length > 0 ? (
                <div className="grid gap-2">
                  {workerEntries.map((entry) => (
                    <WorkerHealthCard
                      key={entry.name}
                      name={entry.name}
                      probe={{
                        ok: entry.ok,
                        status_code: entry.status_code,
                        ready: entry.ready,
                      }}
                    />
                  ))}
                </div>
              ) : pipelineQuery.isError && fleetQuery.isError ? (
                <p className="text-sm text-red-700">Could not load worker probes.</p>
              ) : (
                <p className="text-sm text-ink-soft">No workers discovered yet.</p>
              )}
            </div>
          </div>
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
