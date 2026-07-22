import type { ReactNode } from 'react'

import { NavMenu } from '@/components/NavMenu'
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

function RoleStatusBanner() {
  const { me, isError, error, isLoading } = useAuth()
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
  return (
    <div
      className="border-b border-line bg-panel/60 px-4 py-1 text-center text-[0.65rem] text-mute"
      role="status"
    >
      {me.email} · {me.role.replace(/_/g, ' ')}
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
