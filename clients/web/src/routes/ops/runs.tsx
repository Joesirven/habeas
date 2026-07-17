import { RoleGate, RouteShell } from '@/lib/auth'

export function OpsRunsPage() {
  return (
    <RoleGate allow={(role) => role === 'super_admin'}>
      <RouteShell
        eyebrow="Ops · Run"
        title="Runs"
        description="Job attempts across DROP workers — list, filters, and run detail ship next."
      />
    </RoleGate>
  )
}
