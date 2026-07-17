import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Skeleton } from '@/components/AppShell'
import {
  approveMatchingReview,
  listMatchingReviewApprovals,
  type ApprovalRecord,
} from '@/lib/api'

function MatchingReviewTableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <table className="min-w-full text-left text-sm" role="status" aria-label="Loading approvals">
      <thead className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th className="px-4 py-3">
            <Skeleton className="h-3 w-20" />
          </th>
          <th className="px-4 py-3">
            <Skeleton className="h-3 w-16" />
          </th>
          <th className="px-4 py-3">
            <Skeleton className="h-3 w-12" />
          </th>
          <th className="px-4 py-3">
            <Skeleton className="h-3 w-14" />
          </th>
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, index) => (
          <tr key={index} className="border-b border-slate-800/80">
            <td className="px-4 py-3">
              <Skeleton className="h-4 w-40" />
            </td>
            <td className="px-4 py-3">
              <Skeleton className="h-4 w-36" />
            </td>
            <td className="px-4 py-3">
              <Skeleton className="h-4 w-24" />
            </td>
            <td className="px-4 py-3">
              <Skeleton className="h-7 w-20 rounded-lg" />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function MatchingReviewPage() {
  const queryClient = useQueryClient()
  const approvalsQuery = useQuery({
    queryKey: ['admin-api', 'approvals', 'matching.review'],
    queryFn: () => listMatchingReviewApprovals('pending'),
    refetchInterval: 15_000,
  })

  const approveMutation = useMutation({
    mutationFn: (approval: ApprovalRecord) =>
      approveMatchingReview(approval.id, { decided_by: 'web-admin@habeas.com' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'approvals'] })
    },
  })

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Matching review</h2>
        <p className="mt-2 max-w-2xl text-slate-400">
          Approve matching.review gates before fulfillment dispatch can proceed.
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
        {approvalsQuery.isPending && <MatchingReviewTableSkeleton />}
        {approvalsQuery.isError && (
          <p className="p-6 text-red-300">Could not load matching.review approvals.</p>
        )}
        {approvalsQuery.isSuccess && approvalsQuery.data.length === 0 && (
          <p className="p-6 text-slate-400">No pending matching.review items.</p>
        )}
        {approvalsQuery.isSuccess && approvalsQuery.data.length > 0 && (
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Approval</th>
                <th className="px-4 py-3">Request</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {approvalsQuery.data.map((approval) => {
                const isApproving =
                  approveMutation.isPending && approveMutation.variables?.id === approval.id
                return (
                  <tr key={approval.id} className="border-b border-slate-800/80 text-slate-200">
                    <td className="px-4 py-3 font-mono text-xs">{approval.id}</td>
                    <td className="px-4 py-3 font-mono text-xs">{approval.request_id}</td>
                    <td className="px-4 py-3">{approval.approver_role ?? '—'}</td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                        disabled={approveMutation.isPending}
                        onClick={() => approveMutation.mutate(approval)}
                      >
                        {isApproving ? (
                          <>
                            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-emerald-400/50 border-t-white" />
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
