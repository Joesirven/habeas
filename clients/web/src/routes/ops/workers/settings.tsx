import { Link, useSearch } from '@tanstack/react-router'
import { type ReactNode } from 'react'

import { RoleGate, isSuperAdmin } from '@/lib/auth'
import { FleetHealthPanel } from '@/routes/ops/workers/FleetHealthPanel'
import { RetryConfigPanel } from '@/routes/ops/workers/RetryConfigPanel'
import { ScheduleConfigPanel } from '@/routes/ops/workers/ScheduleConfigPanel'

function settingsFilterSearch(search: Record<string, unknown>) {
  const worker =
    typeof search.worker === 'string' && search.worker.trim()
      ? search.worker.trim()
      : undefined
  const table =
    typeof search.table === 'string' && search.table.trim()
      ? search.table.trim()
      : undefined
  const health =
    search.health === 'ok' || search.health === 'down' ? search.health : undefined
  return { worker, table, health }
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function WorkersSettingsBody() {
  const filters = settingsFilterSearch(
    useSearch({ strict: false }) as Record<string, unknown>,
  )

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
            Filter views use the URL — no per-worker allowlist.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/ops/workers" className="taste-btn text-xs">
            ← Overview
          </Link>
          <Link to="/ops/connections" className="taste-btn text-xs">
            Connections
          </Link>
          <Link
            to="/ops/workers/settings/tables"
            search={
              {
                worker: filters.worker,
                table: filters.table,
                health: filters.health,
              } as never
            }
            className="taste-btn text-xs"
          >
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
