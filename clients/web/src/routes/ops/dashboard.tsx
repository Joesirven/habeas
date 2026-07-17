import { RoleGate, RouteShell } from '@/lib/auth'

export function OpsDashboardPage() {
  return (
    <RoleGate allow={(role) => role === 'super_admin'}>
      <RouteShell
        eyebrow="Ops"
        title="Ops dashboard"
        description="Prefect-style overview — run volume, failed escalation, and worker pools with time window filters."
      />
    </RoleGate>
  )
}
