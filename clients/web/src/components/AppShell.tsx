import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { useLiveEvents } from '@/lib/live-events'

type AppShellProps = {
  children: ReactNode
}

/** Pulse placeholder for loading panels (dashboard, ops, approvals). */
export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-md bg-slate-800/80 ${className}`}
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

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Habeas</p>
            <h1 className="text-lg font-semibold text-white">Data Privacy Admin</h1>
          </div>
          <nav className="flex gap-4 text-sm text-slate-300">
            <Link
              to="/"
              className="hover:text-white [&.active]:font-medium [&.active]:text-white"
            >
              Dashboard
            </Link>
            <Link
              to="/requests"
              className="hover:text-white [&.active]:font-medium [&.active]:text-white"
            >
              Requests
            </Link>
            <Link
              to="/approvals/matching-review"
              className="hover:text-white [&.active]:font-medium [&.active]:text-white"
            >
              Matching review
            </Link>
            <Link
              to="/ops/drop-pipeline"
              className="hover:text-white [&.active]:font-medium [&.active]:text-white"
            >
              DROP pipeline
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  )
}
