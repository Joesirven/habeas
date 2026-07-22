import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { useMemo, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  getDropWorkers,
  listRuns,
  resolveRunsTimeParams,
  type RunSummary,
  type WorkersTimeWindow,
} from '@/lib/api'
import { RoleGate, isSuperAdmin } from '@/lib/auth'
import type { WorkersFailedSearch } from '@/router'

const WINDOW_OPTIONS: WorkersTimeWindow[] = ['8h', '1w', '3m', 'custom']

/** Fleet worker name → /ops/runs job filter (undefined = no attempt history). */
const WORKER_TO_RUN_JOB: Record<string, string | null> = {
  drop_connector: 'drop_connector',
  drop_ingestor: 'drop_ingestor',
  matching: 'matching',
  hash_index_refresh: 'hash_index_refresh',
  request_dispatcher: null,
  data_fulfillment: null,
}

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

function StatusPill({ status }: { status: string }) {
  const n = status.toLowerCase()
  const variant =
    isFailedStatus(status)
      ? 'fail'
      : n.includes('success') || n.includes('complete') || n === 'ok'
        ? 'ok'
        : n.includes('claim') || n === 'running'
          ? 'run'
          : 'wait'
  return (
    <span className={`taste-status-pill taste-status-${variant}`}>
      <span className="taste-status-dot" aria-hidden />
      {status.replaceAll('_', ' ')}
    </span>
  )
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

function WorkerHistoryBody() {
  const { workerName } = useParams({ from: '/ops/workers/$workerName' })
  const navigate = useNavigate()
  const search = useSearch({ from: '/ops/workers/$workerName' })
  const window = search.window ?? '1w'
  const since = search.since
  const runJob = WORKER_TO_RUN_JOB[workerName]
  const timeParams = resolveRunsTimeParams(window, since)

  const workersQuery = useQuery({
    queryKey: ['ops', 'workers', 'fleet'],
    queryFn: getDropWorkers,
    refetchInterval: 15_000,
  })

  const runsQuery = useQuery({
    queryKey: ['ops', 'workers', workerName, 'runs', window, since],
    queryFn: () =>
      listRuns({
        ...timeParams,
        job: runJob ?? undefined,
        limit: 200,
      }),
    enabled: runJob != null,
    refetchInterval: 15_000,
  })

  const worker = useMemo(
    () => workersQuery.data?.workers.find((item) => item.name === workerName),
    [workersQuery.data?.workers, workerName],
  )

  const runs = runsQuery.data ?? []
  const failedCount = runs.filter((run) => isFailedStatus(run.status)).length

  function patchSearch(patch: Partial<WorkersFailedSearch>) {
    void navigate({
      to: '/ops/workers/$workerName',
      params: { workerName },
      search: {
        window: patch.window ?? window,
        since: patch.since !== undefined ? patch.since : since,
      },
      replace: true,
    })
  }

  return (
    <section className="taste-ops-page space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to="/ops/workers" className="taste-link text-xs">
            ← Workers
          </Link>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              {workerName}
            </h2>
            {worker ? <StatusPill status={worker.ok ? 'ok' : 'failed'} /> : null}
            {runsQuery.isFetching && !runsQuery.isPending ? (
              <span className="taste-frost-chip text-[0.65rem]">Refreshing</span>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-ink-soft">
            Full attempt history for this worker — times, status, and deep links into run detail.
          </p>
        </div>
        <Link
          to="/ops/runs"
          search={{
            job: (runJob ?? undefined) as
              | 'drop_connector'
              | 'drop_ingestor'
              | 'matching'
              | 'hash_index_refresh'
              | undefined,
            window: window === 'custom' ? undefined : window === '3m' ? '3m' : window,
          }}
          className="taste-btn text-xs"
        >
          Open in Runs →
        </Link>
      </header>

      {worker ? (
        <div className="taste-panel grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-5">
          <div>
            <Micro>Pending</Micro>
            <p className="mt-1 text-lg font-medium tabular-nums">{worker.queue.pending}</p>
          </div>
          <div>
            <Micro>Claimed</Micro>
            <p className="mt-1 text-lg font-medium tabular-nums">{worker.queue.claimed}</p>
          </div>
          <div>
            <Micro>In flight</Micro>
            <p className="mt-1 text-lg font-medium tabular-nums">{worker.queue.in_flight}</p>
          </div>
          <div>
            <Micro>Failed terminal</Micro>
            <p className="mt-1 text-lg font-medium tabular-nums text-red-700">
              {worker.queue.failed_terminal}
            </p>
          </div>
          <div>
            <Micro>Oldest pending</Micro>
            <p className="mt-1 text-lg font-medium tabular-nums">
              {worker.queue.oldest_pending_age_seconds == null
                ? '—'
                : formatDuration(worker.queue.oldest_pending_age_seconds)}
            </p>
          </div>
        </div>
      ) : workersQuery.isPending ? (
        <div className="taste-panel p-4">
          <SkeletonLines lines={2} />
        </div>
      ) : (
        <p className="text-xs text-ink-soft">Worker not in current fleet probe.</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {WINDOW_OPTIONS.map((option) => (
          <button
            key={option}
            type="button"
            className={window === option ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
            onClick={() =>
              patchSearch({ window: option, since: option === 'custom' ? since : undefined })
            }
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
                patchSearch({
                  window: 'custom',
                  since: value ? new Date(value).toISOString() : undefined,
                })
              }}
            />
          </label>
        ) : null}
        <span className="ml-auto taste-frost-chip tabular-nums text-[0.65rem]">
          {runs.length} runs · {failedCount} failed
        </span>
      </div>

      <div className="taste-panel overflow-hidden">
        {runJob == null ? (
          <p className="p-4 text-xs text-ink-soft">
            This worker has no attempt table in the Runs union — queue depth only. Proxy actions
            go through admin-api DROP pipeline.
          </p>
        ) : null}
        {runJob != null && runsQuery.isPending ? (
          <div className="p-4">
            <SkeletonLines lines={6} />
          </div>
        ) : null}
        {runJob != null && runsQuery.isError ? (
          <p className="p-4 text-xs text-red-700">
            Could not load run history.
            {runsQuery.error instanceof Error ? (
              <span className="mt-1 block font-mono text-[0.65rem]">
                {runsQuery.error.message}
              </span>
            ) : null}
          </p>
        ) : null}
        {runJob != null && runsQuery.isSuccess && runs.length === 0 ? (
          <p className="p-4 text-xs text-ink-soft">No attempts in this window.</p>
        ) : null}
        {runJob != null && runs.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="taste-table">
              <thead>
                <tr>
                  <th>Run id</th>
                  <th>Status</th>
                  <th>Step</th>
                  <th>Attempt</th>
                  <th>Started</th>
                  <th>Completed</th>
                  <th>Duration</th>
                  <th>Request</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const attemptId = attemptIdFromRun(run)
                  return (
                    <tr key={run.run_id} className="hover:bg-panel/40">
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
                      <td className="font-mono text-xs text-ink-soft">{run.step}</td>
                      <td className="tabular-nums">{run.attempt_number}</td>
                      <td className="whitespace-nowrap tabular-nums text-ink-soft">
                        {run.started_at ? new Date(run.started_at).toLocaleString() : '—'}
                      </td>
                      <td className="whitespace-nowrap tabular-nums text-ink-soft">
                        {run.completed_at ? new Date(run.completed_at).toLocaleString() : '—'}
                      </td>
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
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </section>
  )
}

export function WorkerDetailPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <WorkerHistoryBody />
    </RoleGate>
  )
}
