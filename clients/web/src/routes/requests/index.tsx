import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo, useState } from 'react'

import { Skeleton } from '@/components/AppShell'
import { RequestDetailDrawer } from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { getDropGlobalStats, getNeedsAttention, listRequests } from '@/lib/api'

function RequestsTableSkeleton({ rows = 8 }: { rows?: number }) {
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

function StatTile({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-lg border border-line/80 bg-paper/60 px-4 py-3">
      <p className="taste-micro">{label}</p>
      <p className="mt-1 font-display text-2xl font-medium tabular-nums text-habeas-navy">
        {value}
      </p>
      {hint ? <p className="mt-1 text-[0.65rem] text-mute">{hint}</p> : null}
    </div>
  )
}

export function RequestsPage() {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogRequestId, setDialogRequestId] = useState<string | null>(null)

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

  const statsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-stats-global'],
    queryFn: getDropGlobalStats,
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

  function openTriage(requestId: string) {
    setDialogRequestId(requestId)
    setDialogOpen(true)
  }

  const stats = statsQuery.data

  return (
    <section className="taste-ops-page space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="taste-micro">Requests</p>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              All requests
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

      {stats ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <StatTile label="Open DROP requests" value={stats.open_drop_requests} />
          <StatTile label="Matching review pending" value={stats.matching_review_pending} />
          <StatTile
            label="Matching failed terminal"
            value={stats.matching_failed_terminal}
            hint={
              stats.workers_down > 0
                ? `${stats.workers_down}/${stats.workers_total} workers down`
                : undefined
            }
          />
        </div>
      ) : statsQuery.isPending ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="rounded-lg border border-line/80 bg-paper/60 px-4 py-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-3 h-7 w-12" />
            </div>
          ))}
        </div>
      ) : null}

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
            <table className="taste-table">
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
                      className="group cursor-pointer transition-colors hover:bg-panel/50"
                      onClick={() => openTriage(request.id)}
                    >
                      <td className="whitespace-nowrap tabular-nums text-ink-soft">
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
                          className="relative z-10 font-mono text-xs text-habeas-mid group-hover:text-habeas-navy"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {request.id}
                        </Link>
                      </td>
                      <td className="font-mono text-[0.65rem] text-ink-soft">
                        {request.raw_record_id ?? '—'}
                      </td>
                      <td>
                        {attentionReason ? (
                          <Badge variant="fail" className="normal-case tracking-normal">
                            {attentionReason}
                          </Badge>
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

      <RequestDetailDrawer
        requestId={dialogRequestId}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
      />
    </section>
  )
}
