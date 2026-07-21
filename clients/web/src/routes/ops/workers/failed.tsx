import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useMemo, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  getDropGlobalStats,
  getDropWorkers,
  listRuns,
  resolveRunsTimeParams,
  type RunSummary,
  type WorkersTimeWindow,
} from '@/lib/api'
import { RoleGate, isSuperAdmin } from '@/lib/auth'
import type { WorkersFailedSearch } from '@/router'

const WINDOW_OPTIONS: WorkersTimeWindow[] = ['8h', '1w', '3m', 'custom']

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function formatDuration(seconds: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return s > 0 ? `${m}m ${s}s` : `${m}m`
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

function attemptIdFromRun(run: RunSummary): string {
  const parts = run.run_id.split(':')
  return parts.length > 1 ? parts[parts.length - 1]! : String(run.attempt_number)
}

function FailedMetricsStrip({
  queueFailedTerminal,
  matchingFailedTerminal,
  runCount,
}: {
  queueFailedTerminal: number
  matchingFailedTerminal: number | null
  runCount: number
}) {
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-3 border-b border-line px-3 py-3">
      <div>
        <p className="taste-micro !text-[0.65rem]">Queue failed terminal</p>
        <p className="mt-1 text-lg font-medium tabular-nums text-red-700">{queueFailedTerminal}</p>
      </div>
      <div>
        <p className="taste-micro !text-[0.65rem]">Matching failed terminal</p>
        <p className="mt-1 text-lg font-medium tabular-nums text-red-700">
          {matchingFailedTerminal ?? '—'}
        </p>
      </div>
      <div>
        <p className="taste-micro !text-[0.65rem]">Failed runs in window</p>
        <p className="mt-1 text-lg font-medium tabular-nums text-ink">{runCount}</p>
      </div>
    </div>
  )
}

function FailedRunsBody() {
  const navigate = useNavigate()
  const search = useSearch({ from: '/ops/workers/failed' })
  const window = search.window ?? '1w'
  const since = search.since
  const timeParams = resolveRunsTimeParams(window, since)

  const runsQuery = useQuery({
    queryKey: ['ops', 'workers', 'failed-runs', window, since],
    queryFn: () =>
      listRuns({
        ...timeParams,
        status: 'failed',
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

  const queueFailedTerminal = useMemo(
    () =>
      (workersQuery.data?.workers ?? []).reduce(
        (sum, worker) => sum + worker.queue.failed_terminal,
        0,
      ),
    [workersQuery.data],
  )

  const runs = runsQuery.data ?? []
  const loading = runsQuery.isPending && !runsQuery.data

  function patchSearch(patch: Partial<WorkersFailedSearch>) {
    void navigate({
      to: '/ops/workers/failed',
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
          <Micro>Workers</Micro>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              Failed runs
            </h2>
            {runsQuery.isFetching && !loading ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-ink-soft">
            Terminal failures across worker queues and run attempts in the selected window.
          </p>
        </div>
        <Link to="/ops/workers" search={{ window, since }} className="taste-btn text-xs">
          ← Overview
        </Link>
      </header>

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
      </div>

      <div className="taste-panel overflow-hidden">
        <FailedMetricsStrip
          queueFailedTerminal={queueFailedTerminal}
          matchingFailedTerminal={statsQuery.data?.matching_failed_terminal ?? null}
          runCount={runs.length}
        />

        {runsQuery.isError ? (
          <p className="px-3 py-4 text-xs text-red-700">Could not load failed runs.</p>
        ) : loading ? (
          <div className="p-4">
            <SkeletonLines lines={8} />
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
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-mute">
                      No failed runs in {window}.
                    </td>
                  </tr>
                ) : (
                  runs.map((run) => {
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
                          <span className="taste-status-pill taste-status-fail">
                            <span className="taste-status-dot" aria-hidden />
                            {run.status.replaceAll('_', ' ')}
                          </span>
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

export function WorkersFailedPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <FailedRunsBody />
    </RoleGate>
  )
}
