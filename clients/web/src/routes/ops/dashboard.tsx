import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { opsRunsSearch } from '@/lib/ops-runs-search'
import { useState } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  getDropGlobalStats,
  getDropWorkers,
  listOpsRuns,
  type OpsRunWindow,
} from '@/lib/api'
import { OpsPageChrome, RequireRole } from '@/lib/auth'

const WINDOWS = ['8h', '24h', '1w'] as const satisfies readonly OpsRunWindow[]

const FAIL_STATUSES = new Set(['submit_error', 'outcome_error', 'timeout', 'abandoned'])
const IN_FLIGHT = new Set(['claimed', 'in_flight', 'pending'])

export function OpsDashboardPage() {
  const [window, setWindow] = useState<OpsRunWindow>('24h')

  const statsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-stats-global'],
    queryFn: getDropGlobalStats,
    refetchInterval: 20_000,
  })

  const workersQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-workers'],
    queryFn: getDropWorkers,
    refetchInterval: 20_000,
  })

  const runsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'runs', 'dashboard', window],
    queryFn: () => listOpsRuns({ window, limit: 200 }),
    refetchInterval: 20_000,
  })

  const runs = runsQuery.data?.runs ?? []
  const failed = runs.filter((r) => FAIL_STATUSES.has(r.status))
  const inFlight = runs.filter((r) => IN_FLIGHT.has(r.status))
  const workers = workersQuery.data?.workers ?? []
  const workersUp = workers.filter((w) => w.ok).length

  // Simple volume buckets by hour within window (count bars).
  const bucketHours = window === '8h' ? 8 : window === '24h' ? 24 : 24
  const buckets = Array.from({ length: Math.min(bucketHours, 12) }, () => 0)
  const now = Date.now()
  const spanMs =
    window === '8h' ? 8 * 3600_000 : window === '24h' ? 24 * 3600_000 : 7 * 24 * 3600_000
  for (const run of runs) {
    if (!run.attempted_at) continue
    const t = new Date(run.attempted_at).getTime()
    if (Number.isNaN(t)) continue
    const age = now - t
    if (age < 0 || age > spanMs) continue
    const idx = Math.min(
      buckets.length - 1,
      Math.floor((age / spanMs) * buckets.length),
    )
    // Reverse so left = older, right = newer
    buckets[buckets.length - 1 - idx] += 1
  }
  const maxBucket = Math.max(1, ...buckets)

  return (
    <RequireRole allow={['super_admin']}>
      <OpsPageChrome
        eyebrow="OPS · DASHBOARD"
        title="Ops dashboard"
        support="Prefect-style overview — volume, failed escalation, and worker pools from admin-api (ids/counts only)."
      >
        <div className="flex flex-wrap items-center gap-2">
          <p className="taste-micro mr-2">Window</p>
          {WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => setWindow(w)}
              className={
                window === w
                  ? 'taste-frost-chip border-habeas-mid/40 text-habeas-navy'
                  : 'taste-frost-chip'
              }
            >
              {w}
            </button>
          ))}
          <Link
            to="/ops/runs"
            search={opsRunsSearch({ window, status: 'failed' })}
            className="taste-frost-chip ml-auto"
          >
            Failed runs →
          </Link>
        </div>

        <div className="taste-panel p-5">
          <p className="taste-micro">Volume · {window}</p>
          {runsQuery.isPending ? (
            <div className="mt-4">
              <SkeletonLines lines={2} />
            </div>
          ) : (
            <>
              <div className="mt-4 flex h-16 items-end gap-1">
                {buckets.map((count, i) => (
                  <div
                    key={i}
                    className="flex-1 rounded-sm bg-habeas-mid/70"
                    style={{ height: `${Math.max(8, (count / maxBucket) * 100)}%` }}
                    title={`${count}`}
                  />
                ))}
              </div>
              <table className="taste-table mt-5">
                <tbody>
                  <tr>
                    <td className="!px-0 text-ink-soft">Total in window</td>
                    <td className="!px-0 tabular-nums">{runs.length}</td>
                  </tr>
                  <tr>
                    <td className="!px-0 text-ink-soft">Failed</td>
                    <td className="!px-0 tabular-nums text-red-700">{failed.length}</td>
                  </tr>
                  <tr>
                    <td className="!px-0 text-ink-soft">In flight / pending</td>
                    <td className="!px-0 tabular-nums">{inFlight.length}</td>
                  </tr>
                  <tr>
                    <td className="!px-0 text-ink-soft">Workers up</td>
                    <td className="!px-0 tabular-nums">
                      {workersUp} / {workers.length || '—'}
                    </td>
                  </tr>
                </tbody>
              </table>
            </>
          )}
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <div className="taste-panel-soft p-5">
            <div className="flex items-center justify-between gap-2">
              <p className="taste-micro">Failed escalation</p>
              <Link
                to="/ops/runs"
                search={opsRunsSearch({ status: 'failed', window })}
                className="text-xs text-habeas-mid hover:underline"
              >
                View all
              </Link>
            </div>
            {failed.length === 0 ? (
              <p className="mt-3 text-sm text-ink-soft">No failed attempts in window.</p>
            ) : (
              <table className="taste-table mt-3">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Job</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {failed.slice(0, 8).map((run) => (
                    <tr key={`${run.job}-${run.id}`}>
                      <td className="!py-2">
                        <Link
                          to="/ops/runs/$job/$attemptId"
                          params={{ job: run.job, attemptId: String(run.id) }}
                          className="font-mono text-[0.7rem] text-habeas-mid hover:underline"
                        >
                          {run.job}/{run.id}
                        </Link>
                      </td>
                      <td className="!py-2 text-ink-soft">{run.job}</td>
                      <td className="!py-2 text-red-700">{run.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="taste-panel-soft p-5">
            <p className="taste-micro">Worker pools</p>
            {workersQuery.isPending ? (
              <div className="mt-3">
                <SkeletonLines lines={3} />
              </div>
            ) : workers.length === 0 ? (
              <p className="mt-3 text-sm text-ink-soft">No worker probes.</p>
            ) : (
              <table className="taste-table mt-3">
                <thead>
                  <tr>
                    <th>Worker</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {workers.map((probe) => (
                    <tr key={probe.name}>
                      <td className="!py-2 text-ink">{probe.name}</td>
                      <td className="!py-2">
                        <span
                          className={
                            probe.ok
                              ? 'inline-flex rounded-sm border border-emerald-600/25 bg-emerald-50 px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-[0.08em] text-emerald-800'
                              : 'inline-flex rounded-sm border border-red-600/20 bg-red-50 px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-[0.08em] text-red-800'
                          }
                        >
                          {probe.ok ? 'ok' : 'down'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {statsQuery.data ? (
              <table className="taste-table mt-4">
                <tbody>
                  <tr>
                    <td className="!px-0 text-ink-soft">Review pending</td>
                    <td className="!px-0 tabular-nums">
                      {statsQuery.data.matching_review_pending}
                    </td>
                  </tr>
                  <tr>
                    <td className="!px-0 text-ink-soft">Open DROP</td>
                    <td className="!px-0 tabular-nums">{statsQuery.data.open_drop_requests}</td>
                  </tr>
                </tbody>
              </table>
            ) : null}
          </div>
        </div>
      </OpsPageChrome>
    </RequireRole>
  )
}
