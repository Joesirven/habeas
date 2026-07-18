import { RequireRole, OpsPageChrome } from '@/lib/auth'

export function OpsRunsPage() {
  return (
    <RequireRole allow={['super_admin']}>
      <OpsPageChrome
        eyebrow="OPS · RUNS"
        title="Runs"
        support="Unified job attempts across DROP attempt families. List API and filters land in U5."
      >
        <div className="taste-panel p-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="taste-frost-chip">All</span>
            <span className="taste-frost-chip text-mute">Failed</span>
            <span className="taste-frost-chip text-mute">In progress</span>
            <span className="taste-frost-chip text-mute">Success</span>
          </div>
          <p className="mt-4 text-sm text-ink-soft">Coming in U5 — no runs API yet.</p>
          <div className="mt-5 overflow-x-auto">
            <table className="taste-table">
              <thead>
                <tr>
                  <th>Run id</th>
                  <th>Status</th>
                  <th>Job</th>
                  <th>Request</th>
                  <th>Started</th>
                  <th>Duration</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={6} className="!py-8 text-center text-ink-soft">
                    Empty — awaiting U5 aggregator.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </OpsPageChrome>
    </RequireRole>
  )
}
