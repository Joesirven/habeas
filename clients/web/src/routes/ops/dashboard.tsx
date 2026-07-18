import { RequireRole, OpsPageChrome } from '@/lib/auth'

export function OpsDashboardPage() {
  return (
    <RequireRole allow={['super_admin']}>
      <OpsPageChrome
        eyebrow="OPS · DASHBOARD"
        title="Ops dashboard"
        support="Prefect-style overview shell. Volume strip, tallies, and failed escalation land in U8."
      >
        <div className="taste-panel p-5">
          <p className="taste-micro">Coming in U8</p>
          <p className="mt-3 text-sm text-ink-soft">
            Aggregates and worker-pool cards are not wired yet. Use Runs and Health for live counts
            until the dashboard API lands.
          </p>
          <div className="mt-5 overflow-x-auto">
            <table className="taste-table">
              <thead>
                <tr>
                  <th>Window</th>
                  <th>Total</th>
                  <th>Failed</th>
                  <th>In flight</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="text-ink-soft">24h</td>
                  <td className="tabular-nums text-ink-soft">—</td>
                  <td className="tabular-nums text-ink-soft">—</td>
                  <td className="tabular-nums text-ink-soft">—</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </OpsPageChrome>
    </RequireRole>
  )
}
