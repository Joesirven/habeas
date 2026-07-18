import { Link } from '@tanstack/react-router'

import { RequireRole, OpsPageChrome } from '@/lib/auth'

/** Ops configuration shell — distinct from `/ops/health/configuration` retry config. */
export function OpsConfigurationPage() {
  return (
    <RequireRole allow={['super_admin']}>
      <OpsPageChrome
        eyebrow="OPS · CONFIGURATION"
        title="Configuration"
        support="Ops config shell. Editable concurrency and broader knobs are deferred; retry max_attempts stays under Health."
      >
        <div className="taste-panel p-5 space-y-4">
          <p className="taste-micro">Shell</p>
          <p className="text-sm text-ink-soft">
            This page is not the Health retry editor. Use Health → Configuration for attempt
            floors today.
          </p>
          <Link to="/ops/health/configuration" className="taste-link text-sm">
            Open Health configuration →
          </Link>
        </div>
      </OpsPageChrome>
    </RequireRole>
  )
}
