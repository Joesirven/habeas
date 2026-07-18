import { RequireRole, OpsPageChrome } from '@/lib/auth'

export function OpsIncidentsPage() {
  return (
    <RequireRole allow={['super_admin']}>
      <OpsPageChrome
        eyebrow="OPS · INCIDENTS"
        title="Incidents"
        support="Ack workflow deferred. Honest empty shell until product exists."
      >
        <div className="taste-panel p-5">
          <p className="taste-micro">Coming later</p>
          <p className="mt-3 text-sm text-ink-soft">
            No incident stream in v1. Failed runs escalate via Dashboard / Runs once those APIs
            land (U5/U8).
          </p>
          <div className="mt-5 overflow-x-auto">
            <table className="taste-table">
              <thead>
                <tr>
                  <th>Id</th>
                  <th>Status</th>
                  <th>Opened</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={3} className="!py-8 text-center text-ink-soft">
                    No incidents.
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
