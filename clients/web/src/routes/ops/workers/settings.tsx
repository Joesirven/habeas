import { Link } from '@tanstack/react-router'
import { type ReactNode } from 'react'

import { FleetHealthPanel } from '@/routes/ops/workers/FleetHealthPanel'
import { RetryConfigPanel } from '@/routes/ops/workers/RetryConfigPanel'
import { ScheduleConfigPanel } from '@/routes/ops/workers/ScheduleConfigPanel'
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
            Super admin only. Fleet health, Cloud Scheduler cadences, and per-table retry limits.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/ops/workers" className="taste-btn text-xs">
            ← Overview
          </Link>
          <Link to="/ops/connections" className="taste-btn text-xs">
            Connections
          </Link>
          <Link to="/ops/workers/settings/tables" className="taste-btn text-xs">
            Attempt tables
          </Link>
        </div>
      </header>

      <FleetHealthPanel />
      <ScheduleConfigPanel />
      <RetryConfigPanel />

      <p className="taste-micro text-mute">
        Workers appear when Scheduler or Cloud Run discovery finds them; no UI allowlist.
      </p>
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
