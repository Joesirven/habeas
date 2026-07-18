import { useQuery } from '@tanstack/react-query'
import { useRouterState } from '@tanstack/react-router'
import { useCallback, useState, type ReactNode } from 'react'

import { NavMenu } from '@/components/NavMenu'
import {
  PostAuthSplash,
  markPostAuthSplashSeen,
  shouldPlayPostAuthSplash,
} from '@/components/PostAuthSplash'
import { getAuthMe } from '@/lib/api'
import { useMeQuery } from '@/lib/auth'
import { useLiveEvents } from '@/lib/live-events'

type AppShellProps = {
  children: ReactNode
}

/** Pulse placeholder for loading panels (dashboard, ops, approvals). */
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

export function AppShell({ children }: AppShellProps) {
  useLiveEvents()
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const isSplashLab = pathname.startsWith('/dev/splash-lab')

  const identityQuery = useQuery({
    queryKey: ['admin-api', 'auth', 'me'],
    queryFn: getAuthMe,
    retry: false,
    staleTime: 60_000,
    enabled: !isSplashLab,
  })

  // Warm GET /me for role-aware nav + route gates (shared TanStack Query cache).
  useMeQuery({ enabled: !isSplashLab })

  const [splashOpen, setSplashOpen] = useState(() => shouldPlayPostAuthSplash())

  const finishSplash = useCallback(() => {
    markPostAuthSplashSeen()
    setSplashOpen(false)
  }, [])

  const showSplash =
    !isSplashLab &&
    splashOpen &&
    !identityQuery.isPending &&
    Boolean(identityQuery.data?.authenticated)

  if (showSplash) {
    // Default bumper: CRT Snow Lock (variant 1). Lab at /dev/splash-lab.
    return (
      <PostAuthSplash variant={1} autoFinish durationMs={3400} onDone={finishSplash} />
    )
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header
        className="sticky top-0 z-20 border-b border-[var(--glass-border)]"
        style={{
          WebkitBackdropFilter: 'blur(var(--glass-blur))',
          backdropFilter: 'blur(var(--glass-blur))',
          background:
            'linear-gradient(to right, var(--glass-gradient-start), var(--glass-gradient-end))',
        }}
      >
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-6 py-4">
          <div className="min-w-0">
            <p className="taste-micro">Habeas</p>
            <h1 className="mt-1 font-display text-[1.25rem] font-medium leading-none tracking-tight text-ink">
              Data Privacy
            </h1>
          </div>
          <NavMenu />
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</main>

      <footer className="mt-auto bg-ink">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <p className="text-xs tracking-wide text-white/85">Habeas · Data Privacy</p>
          <p className="text-[0.65rem] uppercase tracking-[0.16em] text-white/45">
            Ops console
          </p>
        </div>
      </footer>
    </div>
  )
}
