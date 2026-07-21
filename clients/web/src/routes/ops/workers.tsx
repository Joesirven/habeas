import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useMemo, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  getDropGlobalStats,
  getDropWorkers,
  listRuns,
  resolveRunsTimeParams,
  type DropWorkerRecord,
  type RunSummary,
  type WorkersTimeWindow,
} from '@/lib/api'
import { RoleGate, isSuperAdmin } from '@/lib/auth'
import type { WorkersSearch, WorkersStatusTab } from '@/router'

const WINDOW_OPTIONS: WorkersTimeWindow[] = ['8h', '1w', '3m', 'custom']

const JOB_OPTIONS = [
  { value: '', label: 'All jobs' },
  { value: 'matching', label: 'matching' },
  { value: 'hash_index_refresh', label: 'hash_index_refresh' },
  { value: 'drop_connector', label: 'drop_connector' },
  { value: 'drop_ingestor', label: 'drop_ingestor' },
] as const

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function isFailedStatus(status: string): boolean {
  const n = status.toLowerCase()
  return (
    n.includes('fail') ||
    n.includes('error') ||
    n === 'failed_terminal' ||
    n === 'abandoned' ||
    n === 'timeout'
  )
}

function isInFlightStatus(status: string): boolean {
  const n = status.toLowerCase()
  return n.includes('claimed') || n === 'running' || n === 'in_flight'
}

function isWaitingStatus(status: string): boolean {
  const n = status.toLowerCase()
  return n.includes('pending') || n.includes('queued') || n.includes('awaiting')
}

function isSuccessStatus(status: string): boolean {
  const n = status.toLowerCase()
  return n.includes('success') || n.includes('complete') || n === 'ok' || n === 'succeeded'
}

function statusPillVariant(status: string): 'ok' | 'fail' | 'run' | 'wait' {
  if (isFailedStatus(status)) return 'fail'
  if (isSuccessStatus(status)) return 'ok'
  if (isInFlightStatus(status)) return 'run'
  if (isWaitingStatus(status)) return 'wait'
  return 'wait'
}

function StatusPill({ status }: { status: string }) {
  const variant = statusPillVariant(status)
  return (
    <span className={`taste-status-pill taste-status-${variant}`}>
      <span className="taste-status-dot" aria-hidden />
      {status.replaceAll('_', ' ')}
    </span>
  )
}

function ageLabel(startedAt: string): string {
  const ms = Date.now() - new Date(startedAt).getTime()
  if (Number.isNaN(ms) || ms < 0) return '—'
  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const rem = minutes % 60
  return rem > 0 ? `${hours}h ${rem}m` : `${hours}h`
}

function formatDuration(seconds: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

function attemptIdFromRun(run: RunSummary): string {
  const parts = run.run_id.split(':')
  return parts.length > 1 ? parts[parts.length - 1]! : String(run.attempt_number)
}

function filterRuns(runs: RunSummary[], tab: WorkersStatusTab): RunSummary[] {
  if (tab === 'failed') return runs.filter((r) => isFailedStatus(r.status))
  if (tab === 'in_flight') return runs.filter((r) => isInFlightStatus(r.status))
  if (tab === 'waiting') return runs.filter((r) => isWaitingStatus(r.status))
  return runs
}

function aggregateWorkers(workers: DropWorkerRecord[]) {
  let pending = 0
  let claimed = 0
  let failedTerminal = 0
  let oldestPending: number | null = null

  for (const worker of workers) {
    pending += worker.queue.pending
    claimed += worker.queue.claimed
    failedTerminal += worker.queue.failed_terminal
    const age = worker.queue.oldest_pending_age_seconds
    if (age != null && (oldestPending == null || age > oldestPending)) {
      oldestPending = age
    }
  }

  return { pending, claimed, failedTerminal, oldestPending }
}

function MetricCell({
  label,
  value,
  tone = 'default',
  hint,
}: {
  label: string
  value: string | number
  tone?: 'default' | 'warn' | 'fail'
  hint?: string
}) {
  const valueClass =
    tone === 'fail'
      ? 'text-red-700'
      : tone === 'warn'
        ? 'text-habeas-mid'
        : 'text-ink'
  return (
    <div className="min-w-[5.5rem] flex-1">
      <p className="taste-micro !text-[0.65rem]">{label}</p>
      <p className={`mt-1 text-lg font-medium tabular-nums leading-none ${valueClass}`}>{value}</p>
      {hint ? <p className="mt-1 text-[0.65rem] text-mute">{hint}</p> : null}
    </div>
  )
}

function RunVolumeSparkline({ runs }: { runs: RunSummary[] }) {
  const buckets = useMemo(() => {
    const count = 12
    const now = Date.now()
    const spanMs = 7 * 24 * 3_600_000
    const start = now - spanMs
    const bucketMs = spanMs / count
    const values = Array.from({ length: count }, () => 0)
    for (const run of runs) {
      const t = new Date(run.started_at).getTime()
      if (t < start || t > now) continue
      const index = Math.min(count - 1, Math.floor((t - start) / bucketMs))
      values[index]! += 1
    }
    return values
  }, [runs])

  const max = Math.max(1, ...buckets)

  return (
    <div className="flex items-end gap-0.5" style={{ height: '2.5rem' }} aria-hidden>
      {buckets.map((count, index) => (
        <div
          key={index}
          className="flex-1 min-w-0 rounded-t-sm bg-habeas-mid/80"
          style={{ height: `${Math.max(count > 0 ? 8 : 2, (count / max) * 100)}%` }}
          title={`${count} runs`}
        />
      ))}
    </div>
  )
}

function WorkersWindowControls({
  window,
  since,
  onChange,
}: {
  window: WorkersTimeWindow
  since?: string
  onChange: (patch: { window?: WorkersTimeWindow; since?: string }) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {WINDOW_OPTIONS.map((option) => (
        <button
          key={option}
          type="button"
          className={window === option ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
          onClick={() => onChange({ window: option, since: option === 'custom' ? since : undefined })}
        >
          {option}
        </button>
      ))}
      {window === 'custom' ? (
        <label className="flex items-center gap-1.5 text-xs text-ink-soft">
          Since
          <input
            type="datetime-local"
            className="rounded-md border border-line bg-paper px-2 py-1 font-mono text-xs"
            value={since ? since.slice(0, 16) : ''}
            onChange={(event) => {
              const value = event.target.value
              onChange({
                window: 'custom',
                since: value ? new Date(value).toISOString() : undefined,
              })
            }}
          />
        </label>
      ) : null}
    </div>
  )
}

function WorkersBody() {
  const navigate = useNavigate()
  const search = useSearch({ from: '/ops/workers' })
  const window = search.window ?? '1w'
  const tab = search.tab ?? 'waiting'
  const job = search.job
  const since = search.since

  const timeParams = resolveRunsTimeParams(window, since)

  const runsQuery = useQuery({
    queryKey: ['ops', 'workers', 'runs', window, since, job],
    queryFn: () =>
      listRuns({
        ...timeParams,
        job: job || undefined,
        limit: 200,
      }),
    refetchInterval: 15_000,
  })

  const workersQuery = useQuery({
    queryKey: ['ops', 'workers', 'fleet'],
    queryFn: getDropWorkers,
    refetchInterval: 15_000,
  })

  const statsQuery = useQuery({
    queryKey: ['ops', 'workers', 'global-stats'],
    queryFn: getDropGlobalStats,
    refetchInterval: 15_000,
  })

  const runs = runsQuery.data ?? []
  const visible = useMemo(() => filterRuns(runs, tab), [runs, tab])
  const workers = workersQuery.data?.workers ?? []
  const workerAgg = useMemo(() => aggregateWorkers(workers), [workers])
  const globalStats = statsQuery.data
  const workersDown = globalStats?.workers_down ?? workers.filter((w) => !w.ok).length
  const matchingWorker = workers.find((w) => w.name === 'matching')

  const refreshedAt = runsQuery.dataUpdatedAt
    ? new Date(runsQuery.dataUpdatedAt).toLocaleTimeString()
    : '—'

  function patchSearch(patch: Partial<WorkersSearch>) {
    void navigate({
      to: '/ops/workers',
      search: {
        window: patch.window ?? window,
        tab: patch.tab ?? tab,
        job: patch.job !== undefined ? patch.job : job,
        since: patch.since !== undefined ? patch.since : since,
      },
      replace: true,
    })
  }

  const loading =
    (runsQuery.isPending && !runsQuery.data) ||
    (workersQuery.isPending && !workersQuery.data)

  return (
    <section className="taste-ops-page space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Workers</Micro>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">Overview</h2>
            {(runsQuery.isFetching || workersQuery.isFetching) && !loading ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-ink-soft">
            Fleet health, queue depth, and run triage — poll 15s · refreshed {refreshedAt}
          </p>
        </div>
        <Link to="/ops/workers/failed" search={{ window, since }} className="taste-btn text-xs">
          Failed runs →
        </Link>
      </header>

      <div className="taste-panel p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex flex-wrap gap-x-6 gap-y-4">
            <MetricCell
              label="Workers down"
              value={workersDown}
              tone={workersDown > 0 ? 'fail' : 'default'}
            />
            <MetricCell
              label="Oldest pending"
              value={
                workerAgg.oldestPending == null
                  ? '—'
                  : formatDuration(workerAgg.oldestPending)
              }
              tone={
                workerAgg.oldestPending != null && workerAgg.oldestPending > 3600
                  ? 'warn'
                  : 'default'
              }
            />
            <MetricCell label="Pending backlog" value={workerAgg.pending} />
            <MetricCell
              label="Failed terminal"
              value={workerAgg.failedTerminal}
              tone={workerAgg.failedTerminal > 0 ? 'fail' : 'default'}
            />
            <MetricCell
              label="Review pending"
              value={globalStats?.matching_review_pending ?? '—'}
              tone={
                (globalStats?.matching_review_pending ?? 0) > 0 ? 'warn' : 'default'
              }
            />
            <MetricCell
              label="Matching claimed"
              value={matchingWorker?.queue.claimed ?? '—'}
              tone={(matchingWorker?.queue.claimed ?? 0) > 0 ? 'warn' : 'default'}
              hint="stall signal"
            />
          </div>
          <div className="w-full max-w-xs shrink-0">
            <p className="taste-micro !text-[0.65rem] mb-1">Run volume (1w)</p>
            <RunVolumeSparkline runs={runs} />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <WorkersWindowControls
          window={window}
          since={since}
          onChange={(patch) => patchSearch(patch)}
        />
        <label className="ml-auto flex items-center gap-1.5 text-xs text-ink-soft">
          Job
          <select
            className="glass rounded-lg px-2 py-1.5 text-xs text-ink"
            value={job ?? ''}
            onChange={(event) =>
              patchSearch({ job: event.target.value ? event.target.value : undefined })
            }
          >
            {JOB_OPTIONS.map((option) => (
              <option key={option.value || 'all'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="taste-panel overflow-hidden">
        <div className="border-b border-line px-3 py-2">
          <Micro>Fleet · workers + queue depth</Micro>
        </div>
        {workersQuery.isError ? (
          <p className="px-3 py-4 text-xs text-red-700">
            Workers probe failed.{' '}
            <button type="button" className="underline" onClick={() => void workersQuery.refetch()}>
              Retry
            </button>
          </p>
        ) : workersQuery.isLoading ? (
          <div className="p-4">
            <SkeletonLines lines={4} />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="taste-table">
              <thead>
                <tr>
                  <th>Worker</th>
                  <th>Ready</th>
                  <th>Pending</th>
                  <th>Claimed</th>
                  <th>In flight</th>
                  <th>Failed terminal</th>
                  <th>Oldest pending</th>
                </tr>
              </thead>
              <tbody>
                {workers.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-mute">
                      No worker records.
                    </td>
                  </tr>
                ) : (
                  workers.map((worker) => (
                    <tr key={worker.name}>
                      <td className="font-mono text-xs">{worker.name}</td>
                      <td>
                        <StatusPill status={worker.ok ? 'ok' : 'failed'} />
                      </td>
                      <td className="tabular-nums">{worker.queue.pending}</td>
                      <td className="tabular-nums">{worker.queue.claimed}</td>
                      <td className="tabular-nums">{worker.queue.in_flight}</td>
                      <td className="tabular-nums text-red-700">{worker.queue.failed_terminal}</td>
                      <td className="tabular-nums text-ink-soft">
                        {worker.queue.oldest_pending_age_seconds == null
                          ? '—'
                          : formatDuration(worker.queue.oldest_pending_age_seconds)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="taste-panel overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
          <Micro>Runs</Micro>
          <div className="flex flex-wrap gap-1">
            {(
              [
                ['failed', 'Failed'],
                ['in_flight', 'In flight'],
                ['waiting', 'Waiting'],
                ['all', 'All'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={tab === value ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
                onClick={() => patchSearch({ tab: value })}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {runsQuery.isError ? (
          <p className="px-3 py-4 text-xs text-red-700">
            Runs fetch failed.{' '}
            <button type="button" className="underline" onClick={() => void runsQuery.refetch()}>
              Retry
            </button>
            {runsQuery.error instanceof Error ? (
              <span className="mt-1 block font-mono text-[0.65rem] text-red-800/80">
                {runsQuery.error.message}
              </span>
            ) : null}
          </p>
        ) : runsQuery.isLoading ? (
          <div className="p-4">
            <SkeletonLines lines={6} />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="taste-table">
              <thead>
                <tr>
                  <th>Run id</th>
                  <th>Status</th>
                  <th>Job</th>
                  <th>Attempt</th>
                  <th>Age</th>
                  <th>Duration</th>
                  <th>Request</th>
                </tr>
              </thead>
              <tbody>
                {visible.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-mute">
                      No runs in {window} for this filter.
                    </td>
                  </tr>
                ) : (
                  visible.map((run) => {
                    const attemptId = attemptIdFromRun(run)
                    return (
                      <tr key={run.run_id}>
                        <td className="max-w-[10rem] truncate font-mono text-xs">
                          <Link
                            to="/ops/runs/$job/$attemptId"
                            params={{ job: run.job, attemptId }}
                            className="text-habeas-mid underline decoration-habeas-mid/30 underline-offset-2"
                          >
                            {run.run_id}
                          </Link>
                        </td>
                        <td>
                          <StatusPill status={run.status} />
                        </td>
                        <td className="font-mono text-xs">{run.job}</td>
                        <td className="tabular-nums">{run.attempt_number}</td>
                        <td className="tabular-nums text-ink-soft">{ageLabel(run.started_at)}</td>
                        <td className="tabular-nums text-ink-soft">
                          {formatDuration(run.duration_seconds)}
                        </td>
                        <td className="font-mono text-xs">
                          {run.request_id ? (
                            <Link
                              to="/requests/$requestId"
                              params={{ requestId: run.request_id }}
                              className="text-habeas-mid underline decoration-habeas-mid/30 underline-offset-2"
                            >
                              {run.request_id.slice(0, 8)}…
                            </Link>
                          ) : (
                            <span className="text-mute">—</span>
                          )}
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}

export function WorkersPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <WorkersBody />
    </RoleGate>
  )
}
