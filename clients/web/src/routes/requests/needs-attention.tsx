import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { SkeletonLines } from '@/components/AppShell'
import { MatchingReviewPage } from '@/routes/approvals/matching-review'
import { listNeedsAttention } from '@/lib/api'
import { OpsPageChrome, RequireRole } from '@/lib/auth'

/** Canonical Needs attention — API queue + matching.review actions. */
export function NeedsAttentionPage() {
  const queueQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'needs-attention'],
    queryFn: () => listNeedsAttention(100),
    refetchInterval: 15_000,
  })

  const items = queueQuery.data?.items ?? []

  return (
    <RequireRole allow={['super_admin', 'admin', 'data_owner']}>
      <OpsPageChrome
        eyebrow="REQUESTS · NEEDS ATTENTION"
        title="Needs attention"
        support="Pending matching.review gates — open a row for the stage journey, or act below."
      >
        <div className="taste-panel overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
            <p className="taste-micro">
              Queue · {queueQuery.data?.count ?? '—'} pending
            </p>
            {queueQuery.isFetching ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>

          {queueQuery.isPending ? (
            <div className="p-4">
              <SkeletonLines lines={4} />
            </div>
          ) : null}

          {queueQuery.isError ? (
            <p className="p-4 text-sm text-red-700">Could not load needs-attention queue.</p>
          ) : null}

          {queueQuery.isSuccess && items.length === 0 ? (
            <p className="p-4 text-sm text-ink-soft">No pending matching.review gates.</p>
          ) : null}

          {items.length > 0 ? (
            <table className="taste-table">
              <thead>
                <tr>
                  <th>Request</th>
                  <th>Reason</th>
                  <th>Stage</th>
                  <th>State</th>
                  <th>Match</th>
                  <th>Requested</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={`${item.request_id}-${item.approval_id}`}>
                    <td className="!py-2">
                      <Link
                        to="/requests/$requestId"
                        params={{ requestId: item.request_id }}
                        className="font-mono text-[0.7rem] text-habeas-mid hover:underline"
                      >
                        {item.request_id}
                      </Link>
                    </td>
                    <td className="!py-2">
                      <span className="taste-frost-chip !normal-case !tracking-normal">
                        {item.attention_reason}
                      </span>
                    </td>
                    <td className="!py-2 text-ink-soft">{item.stage_key}</td>
                    <td className="!py-2 font-mono text-xs">{item.requestor_state ?? '—'}</td>
                    <td className="!py-2 text-ink-soft">
                      {item.match_type ?? '—'}
                      {item.match_count != null ? (
                        <span className="ml-1 tabular-nums">({item.match_count})</span>
                      ) : null}
                    </td>
                    <td className="!py-2 tabular-nums text-ink-soft">
                      {item.requested_at
                        ? new Date(item.requested_at).toLocaleString()
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>

        <div className="mt-6">
          <MatchingReviewPage embedded />
        </div>
      </OpsPageChrome>
    </RequireRole>
  )
}
