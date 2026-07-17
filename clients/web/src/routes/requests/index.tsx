import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { Skeleton } from '@/components/AppShell'
import { listRequests } from '@/lib/api'

function RequestsTableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <table className="min-w-full text-left text-sm" role="status" aria-label="Loading requests">
      <thead className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th className="px-4 py-3">
            <Skeleton className="h-3 w-20" />
          </th>
          <th className="px-4 py-3">
            <Skeleton className="h-3 w-16" />
          </th>
          <th className="px-4 py-3">
            <Skeleton className="h-3 w-24" />
          </th>
          <th className="px-4 py-3">
            <Skeleton className="h-3 w-20" />
          </th>
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, index) => (
          <tr key={index} className="border-b border-slate-800/80">
            <td className="px-4 py-3">
              <Skeleton className="h-4 w-36" />
            </td>
            <td className="px-4 py-3">
              <Skeleton className="h-4 w-28" />
            </td>
            <td className="px-4 py-3">
              <Skeleton className="h-4 w-40" />
            </td>
            <td className="px-4 py-3">
              <Skeleton className="h-4 w-24" />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

export function RequestsPage() {
  const requestsQuery = useQuery({
    queryKey: ['admin-api', 'requests'],
    queryFn: () => listRequests(),
    refetchInterval: 15_000,
  })

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-semibold text-white">Requests</h2>
            {requestsQuery.isFetching && !requestsQuery.isPending && (
              <span className="text-xs text-slate-500">Refreshing…</span>
            )}
          </div>
          <p className="mt-2 text-slate-400">Thin-spine privacy requests across all intake channels.</p>
        </div>
        <Link
          to="/requests/new"
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
        >
          Manual submit
        </Link>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
        {requestsQuery.isPending && <RequestsTableSkeleton />}
        {requestsQuery.isError && (
          <p className="p-6 text-red-300">Could not load requests. Is admin-api running with DATABASE_URL?</p>
        )}
        {requestsQuery.isSuccess && requestsQuery.data.length === 0 && (
          <p className="p-6 text-slate-400">No requests yet.</p>
        )}
        {requestsQuery.isSuccess && requestsQuery.data.length > 0 && (
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Received</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Request ID</th>
                <th className="px-4 py-3">Raw record</th>
              </tr>
            </thead>
            <tbody>
              {requestsQuery.data.map((request) => (
                <tr key={request.id} className="border-b border-slate-800/80 text-slate-200">
                  <td className="px-4 py-3">{new Date(request.received_at).toLocaleString()}</td>
                  <td className="px-4 py-3">{SOURCE_LABELS[request.intake_source] ?? request.intake_source}</td>
                  <td className="px-4 py-3 font-mono text-xs">{request.id}</td>
                  <td className="px-4 py-3">{request.raw_record_id ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
