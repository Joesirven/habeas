import { Link } from '@tanstack/react-router'

import { opsRunsSearch } from '@/lib/ops-runs-search'

import { OpsPageChrome, RequireRole } from '@/lib/auth'

export function OpsIncidentsPage() {
  return (
    <RequireRole allow={['super_admin']}>
      <OpsPageChrome
        eyebrow="OPS · INCIDENTS"
        title="Incidents"
        support="Ack workflow deferred. Failed work is reachable via Runs filters."
      >
        <div className="taste-panel p-5">
          <p className="taste-micro">Shell</p>
          <p className="mt-3 text-sm text-ink-soft">
            No incident stream in v1. Use failed Runs and the Ops dashboard escalation list.
          </p>
          <Link
            to="/ops/runs"
            search={opsRunsSearch({ status: 'failed', window: '24h' })}
            className="taste-btn-primary mt-5 inline-flex text-xs"
          >
            Open failed runs →
          </Link>
        </div>
      </OpsPageChrome>
    </RequireRole>
  )
}
