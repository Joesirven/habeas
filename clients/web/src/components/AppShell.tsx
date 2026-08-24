import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { CommandPalette, useCommandPaletteShortcut } from '@/components/CommandPalette'
import { NavMenu } from '@/components/NavMenu'
import { TourHost } from '@/components/onboarding/TourHost'
import {
  KEYHOLE_SLOT_SLIDE_IN_ID,
  markPostAuthSplashSeen,
  PostAuthSplash,
  shouldPlayPostAuthSplash,
} from '@/components/PostAuthSplash'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Toaster } from '@/components/ui/sonner'
import {
  getStoredSimulateRole,
  setStoredSimulateRole,
  SIMULATE_ROLE_VALUES,
  type MePayload,
  type UserRole,
} from '@/lib/api'
import { AuthProvider, canAccessOwnerPalette, useAuth } from '@/lib/auth'
import { PLATFORM_NAME, PLATFORM_SLUG } from '@/lib/brand'
import { verticalLabel } from '@/lib/legalJourneyLabels'
import { useLiveEvents } from '@/lib/live-events'
import { firstNameFromEmail } from '@/lib/utils'

type AppShellProps = {
  children: ReactNode
}

/** Pulse placeholder for loading panels. */
export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-md bg-line/80 ${className}`}
      aria-hidden="true"
    />
  )
}

export function SkeletonLines({
  lines = 3,
  className = '',
}: {
  lines?: number
  className?: string
}) {
  return (
    <div className={`space-y-3 ${className}`} role="status" aria-label="Loading">
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} className={`h-4 ${index === lines - 1 ? 'w-2/3' : 'w-full'}`} />
      ))}
    </div>
  )
}

function roleLabel(role: UserRole) {
  return role.replace(/_/g, ' ')
}

const CONNECTOR_WELCOME_DISMISSED_PREFIX = `${PLATFORM_SLUG}.connector-welcome.dismissed`

function connectorWelcomeDismissedKey(email: string) {
  return `${CONNECTOR_WELCOME_DISMISSED_PREFIX}:${email.trim().toLowerCase()}`
}

function isConnectorWelcomeDismissed(email: string): boolean {
  try {
    return localStorage.getItem(connectorWelcomeDismissedKey(email)) === '1'
  } catch {
    return false
  }
}

function markConnectorWelcomeDismissed(email: string) {
  try {
    localStorage.setItem(connectorWelcomeDismissedKey(email), '1')
  } catch {
    /* ignore */
  }
}

function isConnectInvitePath(): boolean {
  return (
    typeof window !== 'undefined' && window.location.pathname.startsWith('/connect/')
  )
}

/** OQ12: first assigned SaaS vertical in catalog order (skip Data). */
function primarySetupVerticalId(me: MePayload): string | undefined {
  const labels = me.assigned_vertical_labels ?? []
  const actionableLabel = labels.find((entry) => entry.vertical_id !== 'data')
  if (actionableLabel) return actionableLabel.vertical_id

  const verticals = me.verticals ?? []
  if (!verticals.length) return undefined
  const actionable = verticals.find((id) => id !== 'data')
  return actionable ?? verticals[0]
}

function primarySetupVerticalLabel(me: MePayload, verticalId: string | undefined): string | null {
  if (!verticalId) return null
  const fromApi = me.assigned_vertical_labels?.find(
    (entry) => entry.vertical_id === verticalId,
  )?.display_label
  if (fromApi?.trim()) return fromApi.trim()
  return verticalLabel(verticalId)
}

function shouldShowConnectorWelcome(me: MePayload | undefined): boolean {
  if (!me?.needs_connector_setup) return false
  if (isConnectInvitePath()) return false
  if (isConnectorWelcomeDismissed(me.email)) return false
  return true
}

function welcomeFirstName(me: MePayload): string {
  const given = me.given_name?.trim()
  if (given) return given
  return firstNameFromEmail(me.email)
}

type ConnectorSetupWelcomeProps = {
  me: MePayload
  onDismiss: () => void
  onGetStarted: (verticalId: string) => void
}

function ConnectorSetupWelcome({ me, onDismiss, onGetStarted }: ConnectorSetupWelcomeProps) {
  const verticalId = primarySetupVerticalId(me)
  const verticalName = primarySetupVerticalLabel(me, verticalId)
  const setupLine = verticalName
    ? `Let's set up your ${verticalName} data vertical`
    : "Let's set up your data vertical"

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-paper px-4 py-10">
      <section
        className="w-full max-w-md rounded-xl border border-line bg-white p-6 shadow-sm"
        role="dialog"
        aria-labelledby="connector-welcome-title"
        aria-describedby="connector-welcome-body"
      >
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.12em] text-mute">
          Welcome
        </p>
        <h2
          id="connector-welcome-title"
          className="mt-3 font-display text-xl font-medium tracking-tight text-ink"
        >
          Hello {welcomeFirstName(me)}, welcome to {PLATFORM_NAME}
        </h2>
        <p id="connector-welcome-body" className="mt-3 text-sm leading-relaxed text-ink-soft">
          {setupLine}
        </p>
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" onClick={onDismiss}>
            Maybe later
          </Button>
          <Button
            type="button"
            disabled={!verticalId}
            onClick={() => {
              if (verticalId) onGetStarted(verticalId)
            }}
          >
            Get started
          </Button>
        </div>
      </section>
    </div>
  )
}

function RoleStatusBanner() {
  const { me, isError, error, isLoading, realRole } = useAuth()
  const queryClient = useQueryClient()
  const [simulateRole, setSimulateRole] = useState<UserRole | null>(() => getStoredSimulateRole())
  if (isLoading) return null
  if (isError) {
    return (
      <div
        className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-xs text-amber-950"
        role="status"
      >
        Role API unavailable ({error?.message ?? 'GET /me failed'}). Ops nav is shown for
        discovery; pages stay gated until admin-api identity works.
      </div>
    )
  }
  if (!me) return null

  const showSimulator = realRole === 'super_admin'
  const selectValue = simulateRole ?? me.role
  const meRealRole = me.real_role

  function applySimulateRole(next: UserRole) {
    const stored = next === meRealRole ? null : next
    setStoredSimulateRole(stored)
    setSimulateRole(stored)
    void queryClient.invalidateQueries({ queryKey: ['admin-api', 'me'] })
  }

  return (
    <div className="border-b border-line bg-panel/60 px-4 py-1 text-[0.65rem] text-mute">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-3 gap-y-1">
        <span role="status">
          {me.email} · {roleLabel(me.role)}
          {showSimulator && me.role !== me.real_role ? (
            <span className="text-mute/80"> (real {roleLabel(me.real_role)})</span>
          ) : null}
        </span>
        {showSimulator ? (
          <div className="inline-flex items-center gap-1.5 text-mute">
            <span className="text-[0.65rem] text-mute">View as</span>
            {/* Portaled menu — native <select> closes immediately under sticky + backdrop-blur. */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="rounded border border-line bg-white px-1.5 py-0.5 text-[0.65rem] text-ink-soft outline-none hover:border-habeas-navy/35 focus-visible:border-habeas-navy/40"
                  aria-label="Simulate effective role"
                >
                  {roleLabel(selectValue)} ▾
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="center" className="min-w-[9rem]">
                <DropdownMenuLabel>Effective role</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {SIMULATE_ROLE_VALUES.map((roleOption) => (
                  <DropdownMenuItem
                    key={roleOption}
                    onSelect={() => applySimulateRole(roleOption)}
                    className={
                      roleOption === selectValue
                        ? 'bg-panel font-medium text-habeas-navy'
                        : undefined
                    }
                  >
                    {roleLabel(roleOption)}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function AppShellFrame({ children }: AppShellProps) {
  useLiveEvents()
  const navigate = useNavigate()
  const { role, me } = useAuth()
  const showPalette = canAccessOwnerPalette(role)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const openPalette = useCallback(() => setPaletteOpen(true), [])
  useCommandPaletteShortcut(openPalette)

  // Post-sign-in entrance bumper — fires once per session, right after /me
  // resolves for the first time (not on every app load/reload of an already
  // -signed-in session; shouldPlayPostAuthSplash gates on sessionStorage).
  const [showPostAuthSplash, setShowPostAuthSplash] = useState(false)
  const [showConnectorWelcome, setShowConnectorWelcome] = useState(false)
  const splashTriggered = useRef(false)

  const maybeShowConnectorWelcome = useCallback((profile: MePayload) => {
    if (shouldShowConnectorWelcome(profile)) {
      setShowConnectorWelcome(true)
    }
  }, [])

  const dismissConnectorWelcome = useCallback(() => {
    if (me) markConnectorWelcomeDismissed(me.email)
    setShowConnectorWelcome(false)
  }, [me])

  const startConnectorSetup = useCallback(
    (verticalId: string) => {
      if (me) markConnectorWelcomeDismissed(me.email)
      setShowConnectorWelcome(false)
      void navigate({
        to: '/owner/connectors',
        search: { vertical: verticalId },
      })
    },
    [me, navigate],
  )

  useEffect(() => {
    if (me && !splashTriggered.current) {
      splashTriggered.current = true
      // Owner invite links should open immediately — skip the post-auth bumper.
      const onConnectInvite = isConnectInvitePath()
      if (!onConnectInvite && shouldPlayPostAuthSplash()) {
        setShowPostAuthSplash(true)
      } else {
        if (onConnectInvite) {
          markPostAuthSplashSeen()
        } else {
          markPostAuthSplashSeen()
          maybeShowConnectorWelcome(me)
        }
      }
    }
  }, [me, maybeShowConnectorWelcome])

  if (showPostAuthSplash) {
    return (
      <PostAuthSplash
        variant={KEYHOLE_SLOT_SLIDE_IN_ID}
        autoFinish
        onDone={() => {
          markPostAuthSplashSeen()
          setShowPostAuthSplash(false)
          if (me) maybeShowConnectorWelcome(me)
        }}
      />
    )
  }

  if (showConnectorWelcome && me) {
    return (
      <ConnectorSetupWelcome
        me={me}
        onDismiss={dismissConnectorWelcome}
        onGetStarted={startConnectorSetup}
      />
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <header className="sticky top-0 z-40 overflow-visible border-b border-line bg-white/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 overflow-visible px-4 py-2.5 sm:px-6">
          <div className="min-w-0">
            <h1 className="text-base font-semibold tracking-tight text-ink">{PLATFORM_NAME}</h1>
          </div>
          <div className="relative z-50 flex items-center gap-3 overflow-visible">
            {showPalette ? (
              <button
                type="button"
                onClick={() => setPaletteOpen(true)}
                className="hidden items-center gap-1 rounded border border-line bg-paper px-2 py-1 text-[0.65rem] text-mute transition-colors hover:border-habeas-navy/30 hover:text-ink sm:inline-flex"
                aria-label="Open command palette"
              >
                <span>Search</span>
                <kbd className="rounded border border-line bg-white px-1 font-mono text-[0.6rem]">
                  ⌘K
                </kbd>
              </button>
            ) : null}
            <NavMenu />
          </div>
        </div>
        <RoleStatusBanner />
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-5 sm:px-6">{children}</main>

      {showPalette ? (
        <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      ) : null}

      <Toaster />

      <TourHost />

      <footer className="mt-auto border-t border-line bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <p className="text-xs text-mute">{PLATFORM_NAME}</p>
          <p className="text-[0.65rem] text-mute">Ops</p>
        </div>
      </footer>
    </div>
  )
}

export function AppShell({ children }: AppShellProps) {
  return (
    <AuthProvider>
      <AppShellFrame>{children}</AppShellFrame>
    </AuthProvider>
  )
}
