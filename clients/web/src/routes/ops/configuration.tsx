import { Link } from '@tanstack/react-router'

import { RoleGate, RouteShell, isSuperAdmin } from '@/lib/auth'

export function OpsConfigurationPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <RouteShell
        eyebrow="Workers · Configuration"
        title="Configuration"
        description="Infra-owned until an editable concurrency API exists. Retry knobs live under Workers → Settings."
        note="Prefer Workers → Settings for retry config. Role allowlists and worker URLs are deployed via Cloud Build."
      />
      <p className="mt-4 text-xs">
        <Link to="/ops/workers/settings" className="taste-link">
          Open Workers Settings
        </Link>
      </p>
    </RoleGate>
  )
}
