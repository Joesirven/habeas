import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { getDropGlobalStats } from '@/lib/api'
import { RoleGate, canAccessInsights, useAuth } from '@/lib/auth'

/** Thin Insights — backlog tiles without console power paths. */
export function OpsInsightsPage() {
  const { role } = useAuth()
  const statsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-stats-global', 'insights'],
    queryFn: getDropGlobalStats,
    enabled: canAccessInsights(role),
    refetchInterval: 30_000,
  })

  return (
    <RoleGate allow={canAccessInsights}>
      <section className="taste-ops-page space-y-4">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="taste-micro">Workers</p>
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">Insights</h2>
            <p className="mt-1 text-xs text-ink-soft">
              Thin backlog snapshot. Prefer Workers overview for fleet triage.
            </p>
          </div>
          <Link to="/ops/workers" className="taste-btn text-xs">
            Workers overview
          </Link>
        </header>
        <div className="taste-panel p-5">
          <p className="taste-micro">Backlog snapshot</p>
          {statsQuery.isPending ? (
            <p className="mt-3 text-sm text-ink-soft">Loading…</p>
          ) : null}
          {statsQuery.data ? (
            <table className="taste-table mt-4">
              <tbody>
                <tr>
                  <td className="!px-0 text-ink-soft">Matching review pending</td>
                  <td className="!px-0 tabular-nums">{statsQuery.data.matching_review_pending}</td>
                </tr>
                <tr>
                  <td className="!px-0 text-ink-soft">Matching failed terminal</td>
                  <td className="!px-0 tabular-nums">{statsQuery.data.matching_failed_terminal}</td>
                </tr>
                <tr>
                  <td className="!px-0 text-ink-soft">Workers down</td>
                  <td className="!px-0 tabular-nums">
                    {statsQuery.data.workers_down}/{statsQuery.data.workers_total}
                  </td>
                </tr>
              </tbody>
            </table>
          ) : null}
        </div>
      </section>
    </RoleGate>
  )
}
