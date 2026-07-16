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
          <div className="mt-3 space-y-2 text-red-300">
            <p>Could not reach admin-api.</p>
            <p className="text-sm text-red-200/80">
              {healthQuery.error instanceof Error
                ? healthQuery.error.message
                : String(healthQuery.error)}
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
                Deployed builds need Cloud Run Invoker for{' '}
                <code className="rounded bg-slate-800 px-1 text-xs">allUsers</code> (or IAP).
                API: {import.meta.env.VITE_ADMIN_API_URL}
              </p>
            )}
          </div>
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
