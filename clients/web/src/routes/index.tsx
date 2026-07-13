import { useQuery } from '@tanstack/react-query'

import { getHealth } from '@/lib/api'

export function DashboardPage() {
  const healthQuery = useQuery({
    queryKey: ['admin-api', 'health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
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
        <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">Admin API</h3>
        {healthQuery.isPending && <p className="mt-3 text-slate-300">Checking health…</p>}
        {healthQuery.isError && (
          <p className="mt-3 text-red-300">
            Could not reach admin-api. Start it with{' '}
            <code className="rounded bg-slate-800 px-2 py-1 text-sm">
              uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir
              app/admin_api/src
            </code>
          </p>
        )}
        {healthQuery.isSuccess && (
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
            ) : null}
          </dl>
        )}
      </div>
    </section>
  )
}
