import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState, type ReactNode } from 'react'

import { CommandPalette, useCommandPaletteShortcut } from '@/components/CommandPalette'
import { LegalSettingsSheet } from '@/components/LegalSettingsSheet'
import { NavMenu } from '@/components/NavMenu'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  getStoredSimulateRole,
  setStoredSimulateRole,
  SIMULATE_ROLE_VALUES,
  type UserRole,
} from '@/lib/api'
import { AuthProvider, canAccessLegalSurfaces, useAuth } from '@/lib/auth'
import { useLiveEvents } from '@/lib/live-events'

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

function RoleStatusBanner() {
  const { me, isError, error, isLoading, realRole, role } = useAuth()
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
  const showSettings = canAccessLegalSurfaces(role)
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
        {showSettings ? (
          <div className="inline-flex items-center">
            <LegalSettingsSheet />
          </div>
        ) : null}
      </div>
    </div>
  )
}

function AppShellFrame({ children }: AppShellProps) {
  useLiveEvents()
  const { role } = useAuth()
  const showPalette = canAccessLegalSurfaces(role)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const openPalette = useCallback(() => setPaletteOpen(true), [])
  useCommandPaletteShortcut(openPalette)

  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-2.5 sm:px-6">
          <div className="min-w-0">
            <p className="text-[0.65rem] font-medium uppercase tracking-[0.12em] text-mute">
              Habeas
            </p>
            <h1 className="text-base font-semibold tracking-tight text-ink">Data Privacy</h1>
          </div>
          <div className="flex items-center gap-3">
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

      <footer className="mt-auto border-t border-line bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <p className="text-xs text-mute">Habeas · Data Privacy</p>
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
