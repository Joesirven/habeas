import { Link } from '@tanstack/react-router'
import { type ReactNode } from 'react'

import { RetryConfigPanel } from '@/routes/ops/health/configuration'
import { RoleGate, isSuperAdmin } from '@/lib/auth'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function WorkersSettingsBody() {
  return (
    <section className="taste-ops-page space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Workers</Micro>
          <h2 className="mt-1 font-display text-xl font-medium tracking-tight text-ink">
            Settings
          </h2>
          <p className="mt-1 max-w-xl text-xs text-ink-soft">
            Per-worker retry attempt limits. Reaper applies overrides on the next cycle.
          </p>
        </div>
        <Link to="/ops/workers" className="taste-btn text-xs">
          ← Overview
        </Link>
      </header>

      <RetryConfigPanel />
    </section>
  )
}

export function WorkersSettingsPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <WorkersSettingsBody />
    </RoleGate>
  )
}
