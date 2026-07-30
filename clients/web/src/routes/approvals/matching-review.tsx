import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Skeleton } from '@/components/AppShell'
import {
  approveMatchingReview,
  listMatchingReviewApprovals,
  type ApprovalRecord,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'

function MatchingReviewTableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <table className="taste-table" role="status" aria-label="Loading approvals">
      <thead>
        <tr>
          <th>
            <Skeleton className="h-3 w-20" />
          </th>
          <th>
            <Skeleton className="h-3 w-16" />
          </th>
          <th>
            <Skeleton className="h-3 w-12" />
          </th>
          <th>
            <Skeleton className="h-3 w-14" />
          </th>
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, index) => (
          <tr key={index}>
            <td>
              <Skeleton className="h-4 w-40" />
            </td>
            <td>
              <Skeleton className="h-4 w-36" />
            </td>
            <td>
              <Skeleton className="h-4 w-24" />
            </td>
            <td>
              <Skeleton className="h-7 w-20 rounded-lg" />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

type MatchingReviewPageProps = {
  /** When embedded under Needs attention chrome, skip the legacy hero. */
  embedded?: boolean
}

export function MatchingReviewPage({ embedded = false }: MatchingReviewPageProps) {
  const queryClient = useQueryClient()
  const approvalsQuery = useQuery({
    queryKey: ['admin-api', 'approvals', 'matching.review'],
    queryFn: () => listMatchingReviewApprovals('pending'),
    refetchInterval: 15_000,
  })

  const approveMutation = useMutation({
    mutationFn: (approval: ApprovalRecord) =>
      approveMatchingReview(approval.id, { decided_by: 'web-admin@habeas.com' }),
    onSuccess: (_data, approval) => {
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'approvals'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
      actionToast.success({
        title: 'Matching review approved',
        description: `Request ${approval.request_id}`,
      })
    },
    onError: (error, approval) => {
      actionToast.error({
        title: 'Could not approve',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => approveMutation.mutate(approval),
        },
      })
    },
  })

  return (
    <section className={embedded ? 'space-y-4' : 'space-y-10'}>
      {embedded ? null : (
        <header>
          <p className="taste-micro">Approvals</p>
          <h2 className="mt-3 font-display text-[2.5rem] font-medium leading-none tracking-tight text-ink">
            Matching review
          </h2>
          <p className="mt-3 max-w-xl text-sm text-ink-soft">
            Approve matching review gates before fulfillment dispatch can proceed.
          </p>
        </header>
      )}

      <div className="taste-panel overflow-hidden">
        {approvalsQuery.isPending && <MatchingReviewTableSkeleton />}
        {approvalsQuery.isError && (
          <p className="p-6 text-sm text-red-700">Could not load matching approvals.</p>
        )}
        {approvalsQuery.isSuccess && approvalsQuery.data.length === 0 && (
          <p className="p-6 text-sm text-ink-soft">No pending matching review items.</p>
        )}
        {approvalsQuery.isSuccess && approvalsQuery.data.length > 0 && (
          <table className="taste-table">
            <thead>
              <tr>
                <th>Approval</th>
                <th>Request</th>
                <th>Role</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {approvalsQuery.data.map((approval) => {
                const isApproving =
                  approveMutation.isPending && approveMutation.variables?.id === approval.id
                return (
                  <tr key={approval.id}>
                    <td className="font-mono text-xs text-ink-soft">{approval.id}</td>
                    <td className="font-mono text-xs text-ink-soft">{approval.request_id}</td>
                    <td>{approval.approver_role ?? '—'}</td>
                    <td>
                      <button
                        type="button"
                        className="taste-btn-primary inline-flex items-center gap-2 text-xs"
                        disabled={approveMutation.isPending}
                        onClick={() => approveMutation.mutate(approval)}
                      >
                        {isApproving ? (
                          <>
                            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                            Approving…
                          </>
                        ) : (
                          'Approve'
                        )}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
