import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { useLiveEvents } from '@/lib/live-events'

type AppShellProps = {
  children: ReactNode
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
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  )
}
