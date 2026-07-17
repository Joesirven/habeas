import { RoleGate, RouteShell } from '@/lib/auth'

export function OpsJobsPage() {
  return (
    <RoleGate allow={(role) => role === 'super_admin'}>
      <RouteShell
        eyebrow="Ops · Job"
        title="Jobs"
        description="Registered step and worker catalog — static job definitions with links into filtered Runs."
      />
    </RoleGate>
  )
}
