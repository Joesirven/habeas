import { useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

import { NavMenu } from '@/components/NavMenu'
import {
  getStoredSimulateRole,
  setStoredSimulateRole,
  SIMULATE_ROLE_VALUES,
  type UserRole,
} from '@/lib/api'
import { AuthProvider, useAuth } from '@/lib/auth'
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

  return (
    <div
      className="border-b border-line bg-panel/60 px-4 py-1 text-[0.65rem] text-mute"
      role="status"
    >
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-3 gap-y-1">
        <span>
          {me.email} · {roleLabel(me.role)}
          {showSimulator && me.role !== me.real_role ? (
            <span className="text-mute/80"> (real {roleLabel(me.real_role)})</span>
          ) : null}
        </span>
        {showSimulator ? (
          <label className="inline-flex items-center gap-1.5 text-mute">
            <span className="text-[0.65rem] text-mute">View as</span>
            <select
              className="rounded border border-line bg-white px-1.5 py-0.5 text-[0.65rem] text-ink-soft outline-none focus:border-habeas-navy/40"
              aria-label="Simulate effective role"
              value={selectValue}
              onChange={(event) => {
                const next = event.target.value as UserRole
                const stored = next === me.real_role ? null : next
                setStoredSimulateRole(stored)
                setSimulateRole(stored)
                void queryClient.invalidateQueries({ queryKey: ['admin-api', 'me'] })
              }}
            >
              {SIMULATE_ROLE_VALUES.map((role) => (
                <option key={role} value={role}>
                  {roleLabel(role)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
    </div>
  )
}

function AppShellFrame({ children }: AppShellProps) {
  useLiveEvents()

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
          <NavMenu />
        </div>
        <RoleStatusBanner />
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-5 sm:px-6">{children}</main>

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
