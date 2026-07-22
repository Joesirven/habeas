import { Link } from '@tanstack/react-router'
import { type ReactNode } from 'react'

import { ScheduleConfigPanel } from '@/routes/ops/workers/ScheduleConfigPanel'
import { RoleGate, isSuperAdmin } from '@/lib/auth'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

export function OpsConfigurationPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <section className="taste-ops-page space-y-4">
        <header>
          <Micro>Workers · Configuration</Micro>
          <h2 className="mt-1 font-display text-xl font-medium tracking-tight text-ink">
            Configuration
          </h2>
          <p className="mt-1 max-w-xl text-xs text-ink-soft">
            Live worker schedules from Cloud Scheduler. Retry knobs live under Workers → Settings.
            Role allowlists and worker URLs stay deploy-time.
          </p>
        </header>

        <ScheduleConfigPanel />

        <p className="text-xs">
          <Link to="/ops/workers/settings" className="taste-link">
            Open Workers Settings (schedules + retry)
          </Link>
        </p>
      </section>
    </RoleGate>
  )
}
