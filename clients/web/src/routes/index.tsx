import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { Skeleton, SkeletonLines } from '@/components/AppShell'
import { useMe } from '@/lib/auth'
import { getDropGlobalStats, getHealth, getNeedsAttention } from '@/lib/api'

export function DashboardPage() {
  const { isSuperAdmin, isAdmin } = useMe()

  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention', 'home'],
    queryFn: () => getNeedsAttention(100),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

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
    enabled: isAdmin,
    retry: 2,
    placeholderData: (previous) => previous,
  })

  const attentionCount = attentionQuery.data?.items.length
  const dropStats = dropStatsQuery.data
  const attentionLoading = attentionQuery.isPending && !attentionQuery.data

  return (
    <section className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="taste-micro">Home</p>
          <h2 className="mt-2 font-display text-[2.25rem] font-medium leading-none tracking-tight text-ink sm:text-[2.5rem]">
            Needs me
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {(attentionQuery.isFetching || dropStatsQuery.isFetching) &&
          !attentionLoading &&
          attentionQuery.data ? (
            <span className="taste-frost-chip">Refreshing</span>
          ) : null}
          {healthQuery.data ? (
            <span className="taste-frost-chip tabular-nums">
              API {healthQuery.data.status}
            </span>
          ) : healthQuery.isPending ? (
            <span className="taste-frost-chip">Checking API</span>
          ) : null}
        </div>
      </header>

      <div className="taste-panel-soft p-6 sm:p-7">
        <p className="taste-micro">Needs attention</p>

        {attentionLoading ? (
          <div className="mt-5" role="status" aria-label="Loading needs-attention queue">
            <Skeleton className="h-14 w-24" />
            <div className="mt-4">
              <SkeletonLines lines={2} />
            </div>
          </div>
        ) : null}

        {attentionQuery.isError && !attentionQuery.data ? (
          <p className="mt-4 text-sm text-red-700">Could not load needs-attention queue.</p>
        ) : null}

        {attentionQuery.data ? (
          <div className="mt-4 flex flex-wrap items-end justify-between gap-6">
            <div>
              <p className="font-display text-5xl font-medium tabular-nums text-habeas-navy sm:text-6xl">
                {attentionCount}
              </p>
              <p className="mt-2 text-sm text-ink-soft">
                {attentionCount === 0
                  ? 'Nothing blocking right now.'
                  : 'Requests waiting on human gates or blockers.'}
              </p>
            </div>
            <Link to="/requests/needs-attention" className="taste-btn-primary">
              Open queue →
            </Link>
          </div>
        ) : null}

        {attentionQuery.data && attentionQuery.data.items.length > 0 ? (
          <ul className="mt-6 space-y-2 border-t border-line pt-5">
            {attentionQuery.data.items.slice(0, 4).map((item) => (
              <li key={item.request_id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                <Link
                  to="/requests/$requestId"
                  params={{ requestId: item.request_id }}
                  className="taste-link font-mono text-xs"
                >
                  {item.request_id}
                </Link>
                <span className="text-ink-soft">{item.reason}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2">
        <Link to="/requests" className="taste-btn text-xs">
          All requests →
        </Link>
        {isAdmin ? (
          <Link to="/approvals/matching-review" className="taste-btn text-xs">
            Matching review →
          </Link>
        ) : null}
        {isAdmin ? (
          <Link to="/ops/health" className="taste-btn text-xs">
            Insights →
          </Link>
        ) : null}
      </div>

      {isAdmin && dropStats ? (
        <div className="taste-panel-soft px-5 py-4">
          <p className="taste-micro">Pipeline signals</p>
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <div className="flex items-baseline gap-2">
              <dt className="text-ink-soft">Review pending</dt>
              <dd className="font-medium tabular-nums">{dropStats.matching_review_pending}</dd>
            </div>
            <div className="flex items-baseline gap-2">
              <dt className="text-ink-soft">Open DROP</dt>
              <dd className="font-medium tabular-nums">{dropStats.open_drop_requests}</dd>
            </div>
            <div className="flex items-baseline gap-2">
              <dt className="text-ink-soft">Workers down</dt>
              <dd className="font-medium tabular-nums">
                {dropStats.workers_down}/{dropStats.workers_total}
              </dd>
            </div>
          </dl>
        </div>
      ) : null}

      {isAdmin && dropStatsQuery.isPending && !dropStats ? (
        <div className="taste-panel-soft p-5">
          <SkeletonLines lines={2} />
        </div>
      ) : null}

      {isSuperAdmin ? (
        <div className="relative overflow-hidden rounded-[1.1rem] bg-habeas-navy p-5 sm:p-6">
          <div
            aria-hidden
            className="taste-atmosphere-orb pointer-events-none absolute -right-6 top-0 h-36 w-36 rounded-full bg-habeas-light/30 blur-2xl"
          />
          <div className="relative">
            <p className="taste-micro text-white/55">Ops shortcuts</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link to="/ops/dashboard" className="taste-frost-chip-dark">
                Ops dashboard →
              </Link>
              <Link to="/ops/runs" search={{ window: '24h' }} className="taste-frost-chip-dark">
                Runs →
              </Link>
              <Link
                to="/ops/drop-pipeline"
                search={{ tab: 'home' }}
                className="taste-frost-chip-dark"
              >
                Console →
              </Link>
              <Link
                to="/ops/drop-pipeline"
                search={{ tab: 'matching' }}
                className="taste-frost-chip-dark"
              >
                Pipeline matching →
              </Link>
            </div>
          </div>
        </div>
      ) : null}

      {healthQuery.isError && !healthQuery.data ? (
        <p className="text-sm text-red-700">
          Admin API unreachable — retries automatically.
          {healthQuery.error instanceof Error ? ` ${healthQuery.error.message}` : ''}
        </p>
      ) : null}
    </section>
  )
}
