import { Link } from '@tanstack/react-router'

import { RoleGate, RouteShell } from '@/lib/auth'

export function OpsIncidentsPage() {
  return (
    <RoleGate allow={(role) => role === 'super_admin'}>
      <RouteShell
        eyebrow="Ops"
        title="Incidents"
        description="Escalation inbox shell — v1 routes failed work through Runs filters until ownership and ack ship."
        note="Use Runs with a failed status filter to triage incidents today."
      />
      <p className="text-sm">
        <Link
          to="/ops/runs"
          search={{ status: 'failed' }}
          className="text-ink underline decoration-ink/25 underline-offset-4"
        >
          Open failed Runs
        </Link>
      </p>
    </RoleGate>
  )
}
