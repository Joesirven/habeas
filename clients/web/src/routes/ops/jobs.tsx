import { RequireRole, OpsPageChrome } from '@/lib/auth'

export function OpsJobsPage() {
  return (
    <RequireRole allow={['super_admin']}>
      <OpsPageChrome
        eyebrow="OPS · JOBS"
        title="Jobs"
        support="Job catalog shell. Definitions and launch affordances land with U8."
      >
        <div className="taste-panel p-5">
          <p className="taste-micro">Coming in U8</p>
          <p className="mt-3 text-sm text-ink-soft">
            Placeholder catalog — connector, ingest, matching, hash-index refresh, fulfill.
          </p>
          <div className="mt-5 overflow-x-auto">
            <table className="taste-table">
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Family</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={3} className="!py-8 text-center text-ink-soft">
                    Empty catalog shell.
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
