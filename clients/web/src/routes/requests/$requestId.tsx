import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'

import { SkeletonLines } from '@/components/AppShell'
import {
  RequestDetailBody,
  requestDetailHeaderLabel,
} from '@/components/requests/RequestDetailOverlay'
import { useMe, isLegalAdminPersona } from '@/lib/auth'
import { getRequest, getRequestJourney } from '@/lib/api'

export function RequestDetailPage() {
  const { requestId } = useParams({ from: '/requests/$requestId' })
  const { isSuperAdmin, role } = useMe()
  const legalAdmin = isLegalAdminPersona(role)

  const requestQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestId],
    queryFn: () => getRequest(requestId),
    placeholderData: (previous) => previous,
  })

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey'],
    queryFn: () => getRequestJourney(requestId),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const loading = journeyQuery.isPending && !journeyQuery.data
  const intakeSource =
    journeyQuery.data?.intake_source ?? requestQuery.data?.intake_source ?? 'manual'
  const headerLabel = requestDetailHeaderLabel(
    requestId,
    intakeSource,
    requestQuery.data?.display_label,
  )

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <Link to="/requests" className="taste-link text-xs">
            ← All requests
          </Link>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-2">
            <h2 className="truncate font-mono text-lg font-medium tracking-tight text-ink">
              {headerLabel}
            </h2>
            {journeyQuery.isFetching && !journeyQuery.isPending ? (
              <span className="taste-frost-chip text-[0.65rem]">Refreshing</span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isSuperAdmin ? (
            <Link
              to="/ops/runs"
              search={{ request_id: requestId, window: '1w' }}
              className="taste-btn text-xs"
            >
              Runs for request
            </Link>
          ) : null}
          <Link to="/requests/needs-attention" className="taste-btn text-xs">
            Inbox
          </Link>
        </div>
      </header>

      {loading ? (
        <div className="taste-panel p-4">
          <SkeletonLines lines={5} />
        </div>
      ) : null}

      {journeyQuery.isError ? (
        <div className="taste-panel p-4">
          <p className="text-xs text-red-700">Could not load request journey.</p>
          <p className="mt-2 font-mono text-[0.65rem] text-ink-soft">
            {journeyQuery.error instanceof Error ? journeyQuery.error.message : 'Unknown error'}
          </p>
        </div>
      ) : null}

      {journeyQuery.data ? (
        <div className="taste-panel flex min-h-[32rem] flex-col overflow-hidden">
          <RequestDetailBody
            requestId={requestId}
            variant="page"
            defaultTab={legalAdmin ? 'fulfillment' : 'fulfillment'}
            seedRequest={requestQuery.data}
          />
        </div>
      ) : null}
    </section>
  )
}
