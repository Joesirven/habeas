import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { Skeleton } from '@/components/AppShell'
import { listRequests } from '@/lib/api'

function RequestsTableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <table className="taste-table" role="status" aria-label="Loading requests">
      <thead>
        <tr>
          <th>
            <Skeleton className="h-3 w-20" />
          </th>
          <th>
            <Skeleton className="h-3 w-16" />
          </th>
          <th>
            <Skeleton className="h-3 w-24" />
          </th>
          <th>
            <Skeleton className="h-3 w-20" />
          </th>
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, index) => (
          <tr key={index}>
            <td>
              <Skeleton className="h-4 w-36" />
            </td>
            <td>
              <Skeleton className="h-4 w-28" />
            </td>
            <td>
              <Skeleton className="h-4 w-40" />
            </td>
            <td>
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
    <section className="space-y-10">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="taste-micro">Intake</p>
          <div className="mt-3 flex flex-wrap items-baseline gap-3">
            <h2 className="font-display text-[2.5rem] font-medium leading-none tracking-tight text-ink">
              Requests
            </h2>
            {requestsQuery.isFetching && !requestsQuery.isPending && (
              <span className="taste-frost-chip">Refreshing</span>
            )}
          </div>
          <p className="mt-3 max-w-md text-sm text-ink-soft">
            Thin-spine privacy requests across all intake channels.
          </p>
        </div>
        <Link to="/requests/new" className="taste-btn-primary">
          Manual submit
        </Link>
      </header>

      <div className="taste-panel overflow-hidden">
        {requestsQuery.isPending && <RequestsTableSkeleton />}
        {requestsQuery.isError && (
          <p className="p-6 text-sm text-red-700">
            Could not load requests. Is admin-api running with DATABASE_URL?
          </p>
        )}
        {requestsQuery.isSuccess && requestsQuery.data.length === 0 && (
          <p className="p-6 text-sm text-ink-soft">No requests yet.</p>
        )}
        {requestsQuery.isSuccess && requestsQuery.data.length > 0 && (
          <table className="taste-table">
            <thead>
              <tr>
                <th>Received</th>
                <th>Source</th>
                <th>Request ID</th>
                <th>Raw record</th>
              </tr>
            </thead>
            <tbody>
              {requestsQuery.data.map((request) => (
                <tr key={request.id}>
                  <td>{new Date(request.received_at).toLocaleString()}</td>
                  <td>
                    <span className="taste-frost-chip">
                      {SOURCE_LABELS[request.intake_source] ?? request.intake_source}
                    </span>
                  </td>
                  <td className="font-mono text-xs text-ink-soft">
                    <Link
                      to="/requests/$requestId"
                      params={{ requestId: request.id }}
                      className="text-habeas-mid hover:underline"
                    >
                      {request.id}
                    </Link>
                  </td>
                  <td className="font-mono text-xs text-ink-soft">
                    {request.raw_record_id ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
