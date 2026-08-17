import { useQueries } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { shouldPlayPostAuthSplash } from '@/components/PostAuthSplash'
import { QuickStartTour } from '@/components/onboarding/QuickStartTour'
import { listOwnerConnectors } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  isOwnerQuickStartTourEligible,
  ownerQuickStartTourStepsForRole,
  readTourPersistence,
  readTourSessionDismissed,
  resolveTourStepsWithAnchors,
  shouldDeferTourForOnboardingChrome,
  shouldOfferOwnerQuickStartTour,
  tourUserIdFromEmail,
} from '@/lib/quick-start-tour'

/**
 * Login hook for the owner quick-start tour — mount once inside AppShell after auth resolves.
 */
export function TourHost() {
  const { me, isLoading } = useAuth()
  const [dismissed, setDismissed] = useState(false)

  const userId = tourUserIdFromEmail(me?.email)
  const verticals = me?.verticals ?? []

  const connectorQueries = useQueries({
    queries: verticals.map((verticalId) => ({
      queryKey: ['admin-api', 'owner', 'connectors', verticalId, 'tour'],
      queryFn: () => listOwnerConnectors(verticalId),
      enabled: Boolean(userId) && verticals.length > 0,
      staleTime: 60_000,
    })),
  })

  const connectorsLoading = connectorQueries.some((query) => query.isLoading)
  const connectors = useMemo(
    () => connectorQueries.flatMap((query) => query.data?.connectors ?? []),
    [connectorQueries],
  )

  const onConnectInvitePath =
    typeof window !== 'undefined' && window.location.pathname.startsWith('/connect/')

  const deferForOnboardingChrome = shouldDeferTourForOnboardingChrome({
    me,
    postAuthSplashWouldPlay: shouldPlayPostAuthSplash(),
    onConnectInvitePath,
  })

  const tourSteps = useMemo(() => {
    const roleSteps = ownerQuickStartTourStepsForRole(me?.role)
    return resolveTourStepsWithAnchors(roleSteps)
  }, [me?.role])

  const eligible = isOwnerQuickStartTourEligible({
    role: me?.role,
    verticals,
    connectorReminders: me?.connector_reminders,
    connectors,
  })

  const persistence = userId ? readTourPersistence(userId) : null
  const sessionDismissed = userId ? readTourSessionDismissed(userId) : false

  const shouldOffer =
    !isLoading &&
    !connectorsLoading &&
    !dismissed &&
    userId != null &&
    shouldOfferOwnerQuickStartTour({
      eligible,
      persistence,
      sessionDismissed,
      deferForOnboardingChrome,
      onConnectInvitePath,
    })

  if (!shouldOffer || !userId || tourSteps.length === 0) return null

  return (
    <QuickStartTour
      userId={userId}
      steps={tourSteps}
      onFinish={() => setDismissed(true)}
      onDismiss={() => setDismissed(true)}
    />
  )
}
