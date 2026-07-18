import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { SkeletonLines } from '@/components/AppShell'
import { getDropGlobalStats, getHealth } from '@/lib/api'
import {
  canAccessNeedsAttention,
  isSuperAdmin,
  useMeQuery,
  useOpsRole,
} from '@/lib/auth'

export function DashboardPage() {
  const meQuery = useMeQuery()
  const role = useOpsRole()
  const superAdmin = isSuperAdmin(role)
  const opsRole = canAccessNeedsAttention(role)

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
    enabled: opsRole,
    placeholderData: (previous) => previous,
  })

  const dropStats = dropStatsQuery.data
  const pendingReview = dropStats?.matching_review_pending

  return (
    <section className="space-y-8">
      <header className="max-w-2xl">
        <p className="taste-micro">HOME · NEEDS ME</p>
        <h2 className="mt-2 font-display text-xl font-medium tracking-tight text-ink sm:text-2xl">
          Needs me
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          {meQuery.data?.email
            ? `${meQuery.data.email} · ${meQuery.data.role}`
            : meQuery.isPending
              ? 'Loading session…'
              : 'Session role from GET /me'}
        </p>
      </header>

      <div className="taste-panel p-5 sm:p-6">
        <p className="taste-micro">Needs attention</p>
        {opsRole && dropStatsQuery.isPending && !dropStats ? (
          <div className="mt-4">
            <SkeletonLines lines={2} />
          </div>
        ) : (
          <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="font-display text-3xl tabular-nums text-habeas-navy">
                {opsRole && pendingReview != null ? pendingReview : '—'}
              </p>
              <p className="mt-1 text-sm text-ink-soft">Pending matching.review gates</p>
            </div>
            {opsRole ? (
              <Link to="/requests/needs-attention" className="taste-btn-primary text-xs">
                Open queue →
              </Link>
            ) : null}
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="taste-panel-soft p-5">
          <p className="taste-micro">Shortcuts</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link to="/requests" className="taste-frost-chip">
              Requests →
            </Link>
            {opsRole ? (
              <Link to="/requests/needs-attention" className="taste-frost-chip">
                Needs attention →
              </Link>
            ) : null}
            <Link to="/ops/insights" className="taste-frost-chip">
              Insights →
            </Link>
            {superAdmin ? (
              <>
                <Link to="/ops/dashboard" className="taste-frost-chip">
                  Ops dashboard →
                </Link>
                <Link to="/ops/runs" className="taste-frost-chip">
                  Runs →
                </Link>
                <Link to="/ops/drop-pipeline" search={{ tab: 'home' }} className="taste-frost-chip">
                  Pipeline →
                </Link>
                <Link to="/ops/health" className="taste-frost-chip">
                  Health →
                </Link>
              </>
            ) : null}
          </div>
        </div>

        <div className="taste-panel-soft p-5">
          <div className="flex items-center justify-between gap-3">
            <p className="taste-micro">Admin API</p>
            {(healthQuery.isPending || healthQuery.isFetching) && (
              <span className="taste-frost-chip">Checking</span>
            )}
          </div>
          {healthQuery.isPending && !healthQuery.data ? (
            <div className="mt-4">
              <SkeletonLines lines={2} />
            </div>
          ) : null}
          {healthQuery.isError && !healthQuery.data ? (
            <p className="mt-4 text-sm text-red-700">Could not reach admin-api.</p>
          ) : null}
          {healthQuery.data ? (
            <dl className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="taste-micro">Status</dt>
                <dd className="mt-1 font-display text-xl text-habeas-navy">
                  {healthQuery.data.status}
                </dd>
              </div>
              {healthQuery.data.service ? (
                <div>
                  <dt className="taste-micro">Service</dt>
                  <dd className="mt-1 font-display text-xl text-ink">{healthQuery.data.service}</dd>
                </div>
              ) : null}
            </dl>
          ) : null}
        </div>
      </div>

      {superAdmin ? (
        <div className="taste-panel p-5 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="taste-micro">DROP ops summary</p>
            {(dropStatsQuery.isPending || dropStatsQuery.isFetching) && dropStatsQuery.data ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            Global counts from admin-api — ids and counts only.
          </p>

          {dropStatsQuery.isPending && !dropStats ? (
            <div className="mt-5">
              <SkeletonLines lines={4} />
            </div>
          ) : null}

          {dropStatsQuery.isError && !dropStats ? (
            <p className="mt-5 text-sm text-red-700">Could not load DROP summary.</p>
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
        </div>
      ) : null}
    </section>
  )
}
