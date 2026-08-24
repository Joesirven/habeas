/**
 * Owner quick-start nav tour — eligibility, persistence, and session gates (KD26, KD32, KD33).
 */

import type { ConnectorReminder, MePayload, OwnerConnectorSystem, UserRole } from './api'
import { liveConnectReady } from './owner-connector-ui'

function isLegalAdminPersona(role: UserRole | undefined): boolean {
  return role === 'legal' || role === 'admin'
}

export type TourPersistence = 'completed' | 'skipped'

export const OWNER_TOUR_STORAGE_PREFIX = 'habeas-cli.tour.v1.owner.'
export const OWNER_TOUR_SESSION_PREFIX = 'habeas-cli.tour.v1.session.'

export type OwnerQuickStartTourStepId =
  | 'connectors'
  | 'my-work'
  | 'requests'
  | 'matching-inbox'
  | 'docs'
  | 'ops-connections'

export type OwnerQuickStartTourStep = {
  id: OwnerQuickStartTourStepId
  navLabel: string
  title: string
  body: string
  /** TanStack Router path used to locate the nav anchor. */
  path: string
  /** When true, only match anchors whose pathname equals `path` exactly. */
  exact?: boolean
}

const CONNECTORS_STEP: OwnerQuickStartTourStep = {
  id: 'connectors',
  navLabel: 'Connectors',
  title: 'Connectors',
  body: 'Manage your vertical systems — mode, upload refresh, credential rotation, and cadence.',
  path: '/owner/connectors',
  exact: true,
}

const HOME_STEP: OwnerQuickStartTourStep = {
  id: 'my-work',
  navLabel: 'Home',
  title: 'Home',
  body: 'Home for your assigned vertical — matching, fulfillment after Legal kickoff, and connectors.',
  path: '/',
  exact: true,
}

const REQUESTS_STEP: OwnerQuickStartTourStep = {
  id: 'requests',
  navLabel: 'Requests',
  title: 'Requests',
  body: 'Open privacy requests; request detail holds the journey workbench when your vertical is live.',
  path: '/requests',
  exact: true,
}

const ALL_REQUESTS_STEP: OwnerQuickStartTourStep = {
  id: 'requests',
  navLabel: 'All requests',
  title: 'All requests',
  body: 'Open privacy requests; request detail holds the journey workbench when your vertical is live.',
  path: '/requests',
  exact: true,
}

const INBOX_STEP: OwnerQuickStartTourStep = {
  id: 'matching-inbox',
  navLabel: 'Inbox',
  title: 'Inbox',
  body: 'Items needing attention — matching review, triage, and disposition work for your verticals.',
  path: '/requests/needs-attention',
}

const DOCS_STEP: OwnerQuickStartTourStep = {
  id: 'docs',
  navLabel: 'Docs',
  title: 'Docs',
  body: 'Help, runbooks, and training material.',
  path: '/docs',
  exact: true,
}

/** OQ18 — super_admin cheap variant: Connectors + Pipeline Connections (vertical catalog). */
const OPS_CONNECTIONS_STEP: OwnerQuickStartTourStep = {
  id: 'ops-connections',
  navLabel: 'Connections',
  title: 'Connections',
  body: 'Vertical catalog, owner assignments, gated status, and wizard reset for department connectors.',
  path: '/ops/connections',
}

/** F9 v1 owner chain (default): Connectors → Home → Requests → Inbox → Docs. */
export const OWNER_QUICK_START_TOUR_STEPS: readonly OwnerQuickStartTourStep[] = [
  CONNECTORS_STEP,
  HOME_STEP,
  REQUESTS_STEP,
  INBOX_STEP,
  DOCS_STEP,
] as const

/**
 * Role-filtered tour chain — skips nav items not rendered for the principal (F9, OQ18).
 * `data_owner`: full owner chain; `super_admin`: Connectors + ops Connections only.
 */
export function ownerQuickStartTourStepsForRole(
  role: UserRole | undefined,
): readonly OwnerQuickStartTourStep[] {
  if (role === 'super_admin') {
    return [CONNECTORS_STEP, OPS_CONNECTIONS_STEP]
  }

  const steps: OwnerQuickStartTourStep[] = []

  if (showsOwnerConnectorsNav(role)) {
    steps.push(CONNECTORS_STEP)
  }

  if (role === 'data_owner') {
    steps.push(HOME_STEP)
    steps.push(REQUESTS_STEP)
  } else if (isLegalAdminPersona(role)) {
    steps.push(HOME_STEP)
    steps.push(ALL_REQUESTS_STEP)
  } else {
    steps.push(REQUESTS_STEP)
  }

  steps.push(INBOX_STEP)
  steps.push(DOCS_STEP)

  return steps
}

const CONNECTOR_WELCOME_DISMISSED_PREFIX = 'habeas-cli.connector-welcome.dismissed'

function connectorWelcomeDismissedKey(email: string): string {
  return `${CONNECTOR_WELCOME_DISMISSED_PREFIX}:${email.trim().toLowerCase()}`
}

function isConnectorWelcomeDismissed(email: string): boolean {
  try {
    return localStorage.getItem(connectorWelcomeDismissedKey(email)) === '1'
  } catch {
    return false
  }
}

/** Defer tour while PostAuthSplash or first-run connector welcome is active. */
export function shouldDeferTourForOnboardingChrome(input: {
  me?: MePayload | null
  postAuthSplashWouldPlay?: boolean
  onConnectInvitePath?: boolean
  /** Test hook — when set, overrides localStorage welcome-dismissed lookup. */
  connectorWelcomeDismissed?: boolean
}): boolean {
  if (input.postAuthSplashWouldPlay) return true
  if (input.onConnectInvitePath) return false
  const me = input.me
  if (!me?.needs_connector_setup) return false
  const dismissed =
    input.connectorWelcomeDismissed ?? isConnectorWelcomeDismissed(me.email)
  if (dismissed) return false
  return true
}

/** Drop steps whose nav anchor is not in the header (role gates, closed Pipeline menu). */
export function resolveTourStepsWithAnchors(
  steps: readonly OwnerQuickStartTourStep[],
): readonly OwnerQuickStartTourStep[] {
  if (typeof document === 'undefined') return steps
  const anchored = steps.filter((step) => findTourNavAnchor(step) != null)
  return anchored.length > 0 ? anchored : steps
}

export function ownerTourStorageKey(userId: string): string {
  return `${OWNER_TOUR_STORAGE_PREFIX}${userId}`
}

export function ownerTourSessionKey(userId: string): string {
  return `${OWNER_TOUR_SESSION_PREFIX}${userId}`
}

export function tourUserIdFromEmail(email: string | null | undefined): string | null {
  const trimmed = email?.trim()
  return trimmed ? trimmed.toLowerCase() : null
}

export function readTourPersistence(
  userId: string,
  storage: Pick<Storage, 'getItem'> = localStorage,
): TourPersistence | null {
  try {
    const raw = storage.getItem(ownerTourStorageKey(userId))?.trim()
    if (raw === 'completed' || raw === 'skipped') return raw
    return null
  } catch {
    return null
  }
}

export function writeTourPersistence(
  userId: string,
  value: TourPersistence,
  storage: Storage = localStorage,
): void {
  try {
    storage.setItem(ownerTourStorageKey(userId), value)
  } catch {
    /* ignore quota / private mode */
  }
}

export function clearOwnerQuickStartTourState(
  userId: string,
  storage: Storage = localStorage,
): void {
  try {
    storage.removeItem(ownerTourStorageKey(userId))
  } catch {
    /* ignore */
  }
}

export function readTourSessionDismissed(
  userId: string,
  storage: Pick<Storage, 'getItem'> = sessionStorage,
): boolean {
  try {
    return storage.getItem(ownerTourSessionKey(userId)) === 'dismissed'
  } catch {
    return false
  }
}

export function markTourSessionDismissed(
  userId: string,
  storage: Storage = sessionStorage,
): void {
  try {
    storage.setItem(ownerTourSessionKey(userId), 'dismissed')
  } catch {
    /* ignore */
  }
}

export function clearTourSessionDismissed(
  userId: string,
  storage: Storage = sessionStorage,
): void {
  try {
    storage.removeItem(ownerTourSessionKey(userId))
  } catch {
    /* ignore */
  }
}

export function wizardCompletedAt(
  metadata: Record<string, unknown> | null | undefined,
): string | null {
  const value = metadata?.wizard_completed_at
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

/** KD32 — connect-step test pass (Live ok or Upload upload_ok). */
export function connectorHasPassingConnectionTest(connector: OwnerConnectorSystem): boolean {
  if (connector.display_status === 'needs_setup') return false
  if (connector.last_test_ok === true) return true
  const uploadAt = connector.metadata?.last_successful_upload_at
  if (typeof uploadAt === 'string' && uploadAt.trim()) return true
  return liveConnectReady(connector)
}

export function showsOwnerConnectorsNav(role: UserRole | undefined): boolean {
  return role === 'data_owner' || role === 'admin' || role === 'super_admin'
}

export type OwnerQuickStartTourEligibilityInput = {
  role: UserRole | undefined
  verticals: string[] | undefined
  connectorReminders: ConnectorReminder[] | undefined
  connectors: OwnerConnectorSystem[] | undefined
}

/**
 * KD32 — eligible after wizard Confirm + passing connect test; not while any connector
 * is still `needs_setup` or carries a `wizard_incomplete` reminder.
 */
export function isOwnerQuickStartTourEligible(
  input: OwnerQuickStartTourEligibilityInput,
): boolean {
  if (!showsOwnerConnectorsNav(input.role)) return false

  const connectors = input.connectors ?? []
  if (connectors.length === 0) return false

  if (connectors.some((connector) => connector.display_status === 'needs_setup')) {
    return false
  }

  if ((input.connectorReminders ?? []).some((reminder) => reminder.code === 'wizard_incomplete')) {
    return false
  }

  return connectors.some(
    (connector) =>
      wizardCompletedAt(connector.metadata) != null &&
      connectorHasPassingConnectionTest(connector),
  )
}

export type ShouldOfferOwnerQuickStartTourInput = {
  eligible: boolean
  persistence: TourPersistence | null
  sessionDismissed: boolean
  /** PostAuthSplash or first-login welcome still visible. */
  deferForOnboardingChrome?: boolean
  /** Owner invite redeem path — never tour during connect token flow. */
  onConnectInvitePath?: boolean
}

/** KD33 — re-offer each login until completed/skipped; mid-chain dismiss waits for next session. */
export function shouldOfferOwnerQuickStartTour(
  input: ShouldOfferOwnerQuickStartTourInput,
): boolean {
  if (!input.eligible) return false
  if (input.persistence === 'completed' || input.persistence === 'skipped') return false
  if (input.sessionDismissed) return false
  if (input.deferForOnboardingChrome) return false
  if (input.onConnectInvitePath) return false
  return true
}

export function findTourNavAnchor(step: OwnerQuickStartTourStep): HTMLElement | null {
  if (typeof document === 'undefined') return null
  const links = Array.from(document.querySelectorAll<HTMLAnchorElement>('header a[href]'))
  const normalizedPath = step.path
  const match =
    links.find((link) => {
      const href = link.getAttribute('href') ?? ''
      const pathname = href.split('?')[0]?.split('#')[0] ?? ''
      if (step.exact) return pathname === normalizedPath
      return pathname === normalizedPath || pathname.startsWith(`${normalizedPath}/`)
    }) ?? null
  if (match) return match

  // Pipeline dropdown children mount only when open — anchor Pipeline umbrella for ops routes.
  if (normalizedPath.startsWith('/ops/')) {
    return (
      links.find((link) => {
        const href = link.getAttribute('href') ?? ''
        const pathname = href.split('?')[0]?.split('#')[0] ?? ''
        return pathname === '/ops/drop-pipeline'
      }) ?? null
    )
  }

  return null
}
