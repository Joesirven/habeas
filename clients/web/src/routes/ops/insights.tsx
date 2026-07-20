import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { getDropGlobalStats } from '@/lib/api'
import { OpsPageChrome, canAccessNeedsAttention, isSuperAdmin, useOpsRole } from '@/lib/auth'

/** Thin Insights for all resolved roles — fleet view without console power paths. */
export function OpsInsightsPage() {
  const role = useOpsRole()
  const opsRole = canAccessNeedsAttention(role)
  const statsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-stats-global', 'insights'],
    queryFn: getDropGlobalStats,
    enabled: opsRole,
    refetchInterval: 30_000,
  })

  return (
    <OpsPageChrome
      eyebrow="OPS · INSIGHTS"
      title="Insights"
      support="Thin fail-rate / backlog tile. Health remains the deep fleet console for super_admin."
    >
      <div className="taste-panel p-5">
        <p className="taste-micro">Backlog snapshot</p>
        {opsRole && statsQuery.isPending ? (
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
                  {statsQuery.data.workers_down} / {statsQuery.data.workers_total}
                </td>
              </tr>
            </tbody>
          </table>
        ) : (
          <p className="mt-3 text-sm text-ink-soft">
            Stats require an ops role session (GET /me).
          </p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          {opsRole ? (
            <Link to="/requests/needs-attention" className="taste-frost-chip">
              Needs attention →
            </Link>
          ) : null}
          {isSuperAdmin(role) ? (
            <Link to="/ops/health" className="taste-frost-chip">
              Health →
            </Link>
          ) : null}
        </div>
      </div>
    </OpsPageChrome>
  )
}
