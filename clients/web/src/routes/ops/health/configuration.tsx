import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { type ReactNode } from 'react'

import { getRetryConfig } from '@/lib/api'
import { RoleGate, isSuperAdmin } from '@/lib/auth'
import { RetryConfigPanel } from '@/routes/ops/workers/RetryConfigPanel'

export { RetryConfigPanel } from '@/routes/ops/workers/RetryConfigPanel'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

export function HealthConfigurationPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <HealthConfigurationBody />
    </RoleGate>
  )
}

function HealthConfigurationBody() {
  const configQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'retry-config'],
    queryFn: getRetryConfig,
    refetchInterval: 30_000,
    placeholderData: (previous) => previous,
  })

  const floor = configQuery.data?.floor ?? 4

  return (
    <section className="space-y-12">
      <header className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
        <div>
          <Micro>Health</Micro>
          <h2 className="mt-3 max-w-md font-display text-[2.75rem] font-medium leading-[1.05] tracking-tight text-ink sm:text-[3.25rem]">
            Configuration
          </h2>
          <p className="mt-3 text-sm text-ink-soft">
            <Link
              to="/ops/connections"
              className="text-habeas-mid underline decoration-habeas-mid/30 underline-offset-2"
            >
              Connections
            </Link>
          </p>
        </div>
        <p className="max-w-sm border-l border-line pl-5 text-sm leading-relaxed text-ink-soft">
          Per-worker retry attempts via admin-api. Floor is {floor}. Reaper applies overrides on
          the next cycle.
        </p>
      </header>

      <RetryConfigPanel />

      <p className="text-sm text-ink-soft">
        <Link to="/ops/health" className="underline decoration-ink/25 underline-offset-4">
          ← Health landing
        </Link>
      </p>
    </section>
  )
}
