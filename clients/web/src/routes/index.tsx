import { useQuery } from '@tanstack/react-query'

import { Skeleton, SkeletonLines } from '@/components/AppShell'
import { getHealth } from '@/lib/api'

export function DashboardPage() {
  const healthQuery = useQuery({
    queryKey: ['admin-api', 'health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: 3,
    retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 8_000),
    placeholderData: (previous) => previous,
  })

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Dashboard</h2>
        <p className="mt-2 max-w-2xl text-slate-400">
          Admin control plane for privacy request intake, approvals, and operational visibility.
        </p>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">Admin API</h3>
          {(healthQuery.isPending || healthQuery.isFetching) && (
            <span className="text-xs text-slate-500">Checking…</span>
          )}
        </div>

        {healthQuery.isPending && !healthQuery.data && (
          <div className="mt-4" role="status" aria-label="Loading admin API health">
            <SkeletonLines lines={3} />
          </div>
        )}

        {healthQuery.isError && !healthQuery.data && (
          <div className="mt-3 space-y-2 text-red-300">
            <p>Could not reach admin-api.</p>
            <p className="text-sm text-red-200/80">
              {healthQuery.error instanceof Error
                ? healthQuery.error.message
                : String(healthQuery.error)}
            </p>
            <p className="text-sm text-slate-400">
              Waiting for the API / Cloud Run cold start — retries automatically.
            </p>
            {!import.meta.env.VITE_ADMIN_API_URL ? (
              <p className="text-sm text-slate-400">
                Locally, start it with{' '}
                <code className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200">
                  uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir
                  app/admin_api/src
                </code>
              </p>
            ) : (
              <p className="text-sm text-slate-400">
                Deployed API: {import.meta.env.VITE_ADMIN_API_URL}
              </p>
            )}
          </div>
        )}

        {healthQuery.data && (
          <dl className="mt-4 grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase text-slate-500">Status</dt>
              <dd className="text-lg text-emerald-300">{healthQuery.data.status}</dd>
            </div>
            {healthQuery.data.service ? (
              <div>
                <dt className="text-xs uppercase text-slate-500">Service</dt>
                <dd className="text-lg text-white">{healthQuery.data.service}</dd>
              </div>
            ) : (
              <div>
                <dt className="text-xs uppercase text-slate-500">Service</dt>
                <dd>
                  <Skeleton className="mt-1 h-6 w-32" />
                </dd>
              </div>
            )}
          </dl>
        )}
      </div>
    </section>
  )
}
