import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  approveMatchingReview,
  listMatchingReviewApprovals,
  type ApprovalRecord,
} from '@/lib/api'

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
        {approvalsQuery.isPending && <p className="p-6 text-slate-300">Loading approvals…</p>}
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
              {approvalsQuery.data.map((approval) => (
                <tr key={approval.id} className="border-b border-slate-800/80 text-slate-200">
                  <td className="px-4 py-3 font-mono text-xs">{approval.id}</td>
                  <td className="px-4 py-3 font-mono text-xs">{approval.request_id}</td>
                  <td className="px-4 py-3">{approval.approver_role ?? '—'}</td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                      disabled={approveMutation.isPending}
                      onClick={() => approveMutation.mutate(approval)}
                    >
                      Approve
                    </button>
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
