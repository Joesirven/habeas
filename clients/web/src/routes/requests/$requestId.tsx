import { useQuery } from '@tanstack/react-query'
import { Link, useParams, useRouterState, useSearch } from '@tanstack/react-router'

import { SkeletonLines } from '@/components/AppShell'
import {
  RequestDetailBody,
  requestDetailHeaderLabel,
} from '@/components/requests/RequestDetailOverlay'
import { useMe } from '@/lib/auth'
import {
  getOwnerVerticalMatchingResults,
  getRequest,
  getRequestJourney,
} from '@/lib/api'
import { isRequestUuid } from '@/lib/utils'

/** Raw `?system=` even when this route's validateSearch omits the key. */
function useLocationSystemParam(): string | null {
  const href = useRouterState({ select: (state) => state.location.href })
  try {
    const queryIndex = href.indexOf('?')
    if (queryIndex < 0) return null
    const value = new URLSearchParams(href.slice(queryIndex)).get('system')?.trim()
    return value ? value : null
  } catch {
    return null
  }
}

export function RequestDetailPage() {
  const { requestId } = useParams({ from: '/requests/$requestId' })
  const search = useSearch({ from: '/requests/$requestId' })
  const locationSystem = useLocationSystemParam()
  const { isSuperAdmin, role } = useMe()
  const ownerPersona = role === 'data_owner' || role === 'data_user'
  const requestSearch = search as { vertical?: string; system?: string }
  const ownerVertical = ownerPersona ? requestSearch.vertical?.trim() || null : null
  const ownerSystem = ownerPersona
    ? locationSystem ?? (requestSearch.system?.trim() || null)
    : null

  const requestQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestId],
    queryFn: () => getRequest(requestId),
    enabled: isRequestUuid(requestId),
    placeholderData: (previous) => previous,
  })

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey'],
    queryFn: () => getRequestJourney(requestId),
    enabled: isRequestUuid(requestId),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const ownerMatchingQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      requestId,
      'verticals',
      ownerVertical,
      'matching-results',
      ownerSystem,
    ],
    queryFn: () =>
      getOwnerVerticalMatchingResults(
        requestId,
        ownerVertical!,
        ownerSystem ?? undefined,
      ),
    enabled: ownerPersona && isRequestUuid(requestId) && Boolean(ownerVertical),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const requestIdReady = isRequestUuid(requestId)
  const loading = requestIdReady && journeyQuery.isPending && !journeyQuery.data
  const intakeSource =
    journeyQuery.data?.intake_source ?? requestQuery.data?.intake_source ?? 'manual'
  const headerLabel = requestDetailHeaderLabel(
    requestId,
    intakeSource,
    requestQuery.data?.display_label,
  )

  return (
    <section className="flex h-[calc(100vh-5rem)] flex-col gap-2">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <Link to="/requests" className="taste-link text-[0.7rem]">
            {ownerPersona ? '← Requests' : '← All requests'}
          </Link>
          <div className="mt-0.5 flex flex-wrap items-baseline gap-2">
            <h2 className="truncate font-mono text-sm font-medium tracking-tight text-ink">
              {headerLabel}
            </h2>
            {(journeyQuery.isFetching || ownerMatchingQuery.isFetching) &&
            !journeyQuery.isPending ? (
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
        </div>
      </header>

      {loading ? (
        <div className="taste-panel p-4">
          <SkeletonLines lines={5} />
        </div>
      ) : null}

      {!requestIdReady ? (
        <div className="taste-panel p-4">
          <p className="text-xs text-red-700">Could not load request journey.</p>
          <p className="mt-2 font-mono text-[0.65rem] text-ink-soft">
            Invalid request id — open a row from the inbox queue.
          </p>
        </div>
      ) : null}

      {requestIdReady && journeyQuery.isError ? (
        <div className="taste-panel p-4">
          <p className="text-xs text-red-700">Could not load request journey.</p>
          <p className="mt-2 font-mono text-[0.65rem] text-ink-soft">
            {journeyQuery.error instanceof Error ? journeyQuery.error.message : 'Unknown error'}
          </p>
        </div>
      ) : null}

      {requestIdReady && journeyQuery.data ? (
        <div className="taste-panel flex min-h-0 flex-1 flex-col overflow-hidden">
          <RequestDetailBody
            requestId={requestId}
            variant="page"
            defaultTab={ownerPersona ? 'matching' : 'fulfillment'}
            seedRequest={requestQuery.data}
            vertical={ownerVertical}
            system={ownerSystem}
          />
        </div>
      ) : null}
    </section>
  )
}
