import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { Skeleton, SkeletonLines } from '@/components/AppShell'
import { getDropGlobalStats, getHealth } from '@/lib/api'

export function DashboardPage() {
  const healthQuery = useQuery({
    queryKey: ['admin-api', 'health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: 3,
    retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 8_000),
    placeholderData: (previous) => previous,
  })

  const dropStatsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-stats-global'],
    queryFn: getDropGlobalStats,
    refetchInterval: 15_000,
    retry: 2,
    placeholderData: (previous) => previous,
  })

  const dropStats = dropStatsQuery.data

  return (
    <section className="space-y-12">
      <header className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
        <div>
          <p className="taste-micro">Control plane</p>
          <h2 className="mt-3 max-w-md font-display text-[2.75rem] font-medium leading-[1.05] tracking-tight text-ink sm:text-[3.25rem]">
            Dashboard
          </h2>
        </div>
        <p className="max-w-sm border-l border-line pl-5 text-sm leading-relaxed text-ink-soft">
          Admin control plane for privacy request intake, approvals, and operational visibility.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[1fr_1.05fr]">
        <div className="taste-panel-soft p-6 sm:p-7">
          <div className="flex items-center justify-between gap-3">
            <p className="taste-micro">Admin API</p>
            {(healthQuery.isPending || healthQuery.isFetching) && (
              <span className="taste-frost-chip">Checking</span>
            )}
          </div>

          {healthQuery.isPending && !healthQuery.data && (
            <div className="mt-5" role="status" aria-label="Loading admin API health">
              <SkeletonLines lines={3} />
            </div>
          )}

          {healthQuery.isError && !healthQuery.data && (
            <div className="mt-5 space-y-2 text-red-700">
              <p className="text-sm font-medium">Could not reach admin-api.</p>
              <p className="text-sm text-ink-soft">
                {healthQuery.error instanceof Error
                  ? healthQuery.error.message
                  : String(healthQuery.error)}
              </p>
              <p className="text-sm text-ink-soft">
                Waiting for the API / Cloud Run cold start — retries automatically.
              </p>
              {!import.meta.env.VITE_ADMIN_API_URL ? (
                <p className="text-sm text-ink-soft">
                  Locally, start it with{' '}
                  <code className="rounded-md border border-line bg-paper-raised px-2 py-1 font-mono text-xs text-ink">
                    uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir
                    app/admin_api/src
                  </code>
                </p>
              ) : (
                <p className="text-sm text-ink-soft">
                  Deployed API: {import.meta.env.VITE_ADMIN_API_URL}
                </p>
              )}
            </div>
          )}

          {healthQuery.data && (
            <dl className="mt-6 grid gap-5 sm:grid-cols-2">
              <div>
                <dt className="taste-micro">Status</dt>
                <dd className="mt-2 font-display text-2xl text-habeas-navy">
                  {healthQuery.data.status}
                </dd>
              </div>
              {healthQuery.data.service ? (
                <div>
                  <dt className="taste-micro">Service</dt>
                  <dd className="mt-2 font-display text-2xl text-ink">{healthQuery.data.service}</dd>
                </div>
              ) : (
                <div>
                  <dt className="taste-micro">Service</dt>
                  <dd>
                    <Skeleton className="mt-2 h-7 w-32" />
                  </dd>
                </div>
              )}
            </dl>
          )}
        </div>

        <div className="relative min-h-[16rem] overflow-hidden rounded-[1.35rem] bg-habeas-navy">
          <div
            aria-hidden
            className="taste-atmosphere-orb pointer-events-none absolute -left-10 top-6 h-44 w-44 rounded-full bg-habeas-light/35 blur-2xl"
          />
          <div
            aria-hidden
            className="taste-atmosphere-orb pointer-events-none absolute -right-8 bottom-0 h-52 w-52 rounded-full bg-habeas-mid/45 blur-3xl"
            style={{ animationDelay: '1.4s' }}
          />
          <div className="relative flex h-full flex-col justify-between gap-8 p-6 sm:p-7">
            <div className="flex flex-wrap gap-2">
              <span className="taste-frost-chip-dark">Live events</span>
              <span className="taste-frost-chip-dark">Thin spine</span>
            </div>
            <div>
              <p className="taste-micro text-white/55">Shortcuts</p>
              <div className="mt-4 flex flex-wrap gap-3">
                <Link to="/ops/drop-pipeline" search={{ tab: 'home' }} className="taste-frost-chip-dark">
                  Pipeline →
                </Link>
                <Link to="/ops/health" className="taste-frost-chip-dark">
                  Health →
                </Link>
                <Link to="/approvals/matching-review" className="taste-frost-chip-dark">
                  Matching review →
                </Link>
                <Link to="/requests" className="taste-frost-chip-dark">
                  Requests →
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="taste-panel-soft p-6 sm:p-7">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="taste-micro">DROP ops summary</p>
          {(dropStatsQuery.isPending || dropStatsQuery.isFetching) && dropStatsQuery.data ? (
            <span className="taste-frost-chip">Refreshing</span>
          ) : null}
        </div>
        <p className="mt-2 max-w-xl text-sm text-ink-soft">
          Global counts from admin-api — matching review backlog, hash-index in flight, and worker
          health. Ids and counts only.
        </p>

        {dropStatsQuery.isPending && !dropStats ? (
          <div className="mt-5">
            <SkeletonLines lines={4} />
          </div>
        ) : null}

        {dropStatsQuery.isError && !dropStats ? (
          <p className="mt-5 text-sm text-red-700">
            Could not load DROP summary. Pipeline may be unavailable without DATABASE_URL.
          </p>
        ) : null}

        {dropStats ? (
          <div className="mt-5 overflow-x-auto">
            <table className="taste-table">
              <tbody>
                <tr>
                  <td className="!px-0 text-ink-soft">Matching review pending</td>
                  <td className="!px-0 tabular-nums">{dropStats.matching_review_pending}</td>
                </tr>
                <tr>
                  <td className="!px-0 text-ink-soft">Hash index refresh in flight</td>
                  <td className="!px-0 tabular-nums">{dropStats.hash_index_refresh_inflight}</td>
                </tr>
                <tr>
                  <td className="!px-0 text-ink-soft">Workers down</td>
                  <td className="!px-0 tabular-nums">
                    {dropStats.workers_down} / {dropStats.workers_total}
                  </td>
                </tr>
                <tr>
                  <td className="!px-0 text-ink-soft">Open DROP requests</td>
                  <td className="!px-0 tabular-nums">{dropStats.open_drop_requests}</td>
                </tr>
                <tr>
                  <td className="!px-0 text-ink-soft">Matching failed terminal</td>
                  <td className="!px-0 tabular-nums">{dropStats.matching_failed_terminal}</td>
                </tr>
              </tbody>
            </table>
          </div>
        ) : null}

        <div className="mt-5 flex flex-wrap gap-2">
          <Link to="/ops/drop-pipeline" search={{ tab: 'matching' }} className="taste-btn text-xs">
            Pipeline matching →
          </Link>
          <Link to="/ops/health/escalations" className="taste-btn text-xs">
            Escalations →
          </Link>
        </div>
      </div>
    </section>
  )
}
