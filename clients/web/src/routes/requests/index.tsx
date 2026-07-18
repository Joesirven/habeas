import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo } from 'react'

import { Skeleton } from '@/components/AppShell'
import { getNeedsAttention, listRequests } from '@/lib/api'

function RequestsTableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <table
      className="taste-table text-xs [&_td]:py-2 [&_th]:py-2"
      role="status"
      aria-label="Loading requests"
    >
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
          <th>
            <Skeleton className="h-3 w-16" />
          </th>
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, index) => (
          <tr key={index}>
            <td>
              <Skeleton className="h-3.5 w-28" />
            </td>
            <td>
              <Skeleton className="h-3.5 w-20" />
            </td>
            <td>
              <Skeleton className="h-3.5 w-32" />
            </td>
            <td>
              <Skeleton className="h-3.5 w-16" />
            </td>
            <td>
              <Skeleton className="h-3.5 w-24" />
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

  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention'],
    queryFn: () => getNeedsAttention(200),
    refetchInterval: 15_000,
    staleTime: 10_000,
  })

  const attentionByRequestId = useMemo(() => {
    const map = new Map<string, string>()
    for (const item of attentionQuery.data?.items ?? []) {
      map.set(item.request_id, item.reason)
    }
    return map
  }, [attentionQuery.data?.items])

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="taste-micro">Requests</p>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              Where is my DROP?
            </h2>
            {requestsQuery.isFetching && !requestsQuery.isPending && (
              <span className="taste-frost-chip text-[0.65rem]">Refreshing</span>
            )}
            {requestsQuery.isSuccess ? (
              <span className="taste-frost-chip tabular-nums text-[0.65rem]">
                {requestsQuery.data.length} total
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/requests/needs-attention" className="taste-btn text-xs">
            Needs attention
            {attentionQuery.data && attentionQuery.data.items.length > 0 ? (
              <span className="ml-1.5 tabular-nums text-[0.65rem] opacity-80">
                ({attentionQuery.data.items.length})
              </span>
            ) : null}
          </Link>
          <Link to="/requests/new" className="taste-btn-primary text-xs">
            Manual submit
          </Link>
        </div>
      </header>

      <div className="taste-panel overflow-hidden">
        {requestsQuery.isPending && <RequestsTableSkeleton />}
        {requestsQuery.isError && (
          <p className="p-4 text-xs text-red-700">
            Could not load requests. Is admin-api running with DATABASE_URL?
          </p>
        )}
        {requestsQuery.isSuccess && requestsQuery.data.length === 0 && (
          <p className="p-4 text-xs text-ink-soft">No requests yet.</p>
        )}
        {requestsQuery.isSuccess && requestsQuery.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="taste-table text-xs [&_td]:py-2 [&_th]:py-2">
              <thead>
                <tr>
                  <th>Received</th>
                  <th>Source</th>
                  <th>Request ID</th>
                  <th>Raw record</th>
                  <th>Attention</th>
                </tr>
              </thead>
              <tbody>
                {requestsQuery.data.map((request) => {
                  const attentionReason = attentionByRequestId.get(request.id)
                  return (
                    <tr
                      key={request.id}
                      className="group relative transition-colors hover:bg-panel/50"
                    >
                      <td className="whitespace-nowrap tabular-nums text-ink-soft">
                        <Link
                          to="/requests/$requestId"
                          params={{ requestId: request.id }}
                          className="absolute inset-0 z-10"
                          aria-label={`Open request ${request.id}`}
                        />
                        {new Date(request.received_at).toLocaleString()}
                      </td>
                      <td>
                        <span className="taste-frost-chip text-[0.65rem]">
                          {SOURCE_LABELS[request.intake_source] ?? request.intake_source}
                        </span>
                      </td>
                      <td>
                        <Link
                          to="/requests/$requestId"
                          params={{ requestId: request.id }}
                          className="relative z-20 font-mono text-xs text-habeas-mid group-hover:text-habeas-navy"
                        >
                          {request.id}
                        </Link>
                      </td>
                      <td className="font-mono text-[0.65rem] text-ink-soft">
                        {request.raw_record_id ?? '—'}
                      </td>
                      <td>
                        {attentionReason ? (
                          <span className="taste-frost-chip text-[0.65rem] text-red-800">
                            {attentionReason}
                          </span>
                        ) : (
                          <span className="text-ink-soft">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
