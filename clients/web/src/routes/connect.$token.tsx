import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { useMutation, useQuery } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'
import { getConnectInvitePreview, redeemConnectInvite } from '@/lib/api'
import { actionToast } from '@/lib/action-toast'

export function ConnectTokenPage() {
  const navigate = useNavigate()
  const { token } = useParams({ from: '/connect/$token' })
  const previewQuery = useQuery({
    queryKey: ['admin-api', 'connect-invite', token],
    queryFn: () => getConnectInvitePreview(token),
    retry: false,
  })
  const redeemMutation = useMutation({
    mutationFn: () => redeemConnectInvite(token),
    onSuccess: (payload) => {
      actionToast.success({
        title: 'Invite accepted',
        description: `You can review ${payload.vertical_label}.`,
        action: {
          label: 'Open Inbox',
          onClick: () => {
            void navigate({ to: '/requests/needs-attention' })
          },
        },
      })
      void navigate({ to: '/requests/needs-attention' })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not accept invite',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => redeemMutation.mutate(),
        },
      })
    },
  })

  if (previewQuery.isLoading) {
    return (
      <div className="fixed inset-0 z-[60] flex flex-col items-center justify-center bg-[#F8FAFC] px-4">
        <div className="w-full max-w-md rounded-lg border border-[#E2E8F0] bg-white p-6 text-center shadow-sm">
          <p className="text-sm text-[#475569]">Checking invite…</p>
        </div>
      </div>
    )
  }

  if (previewQuery.data?.kind === 'data_user') {
    return (
      <div className="fixed inset-0 z-[60] flex flex-col items-center justify-center bg-[#F8FAFC] px-4">
        <div className="w-full max-w-md space-y-4 rounded-lg border border-[#E2E8F0] bg-white p-6 text-center shadow-sm">
          <p className="text-[0.65rem] font-medium uppercase tracking-[0.12em] text-[#64748B]">
            Data user invite
          </p>
          <h1 className="text-lg font-medium text-[#0F172A]">
            Join {previewQuery.data.vertical_label}
          </h1>
          <p className="text-sm text-[#475569]">
            Accept to review matches, fulfill requests, and refresh this vertical.
          </p>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-center">
            <Button asChild variant="outline">
              <Link to="/" search={{ tab: 'pipeline' }}>
                Cancel
              </Link>
            </Button>
            <Button
              type="button"
              className="bg-habeas-navy hover:bg-habeas-navy/90"
              disabled={redeemMutation.isPending}
              onClick={() => redeemMutation.mutate()}
            >
              {redeemMutation.isPending ? 'Accepting…' : 'Accept invite'}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-[60] flex flex-col items-center justify-center bg-[#F8FAFC] px-4">
      <div className="w-full max-w-md space-y-4 rounded-lg border border-[#E2E8F0] bg-white p-6 text-center shadow-sm">
        <h1 className="text-lg font-medium text-[#0F172A]">Invite link retired</h1>
        <p className="text-sm text-[#475569]">
          This invite link is retired. Open Connectors from the app after you&apos;re assigned a
          vertical.
        </p>
        <Button asChild className="bg-habeas-navy hover:bg-habeas-navy/90">
          <Link to="/owner/connectors">Open Connectors</Link>
        </Button>
      </div>
    </div>
  )
}
