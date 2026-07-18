import { Link } from '@tanstack/react-router'

import { opsRunsSearch } from '@/lib/ops-runs-search'

import { OpsPageChrome, RequireRole } from '@/lib/auth'
import type { OpsRunJob } from '@/lib/api'

const CATALOG: { job: OpsRunJob; label: string; family: string }[] = [
  { job: 'connector', label: 'DROP download', family: 'connector' },
  { job: 'ingest', label: 'Land / promote', family: 'ingest' },
  { job: 'matching', label: 'Matching', family: 'matching' },
  { job: 'hash_index', label: 'Hash index refresh', family: 'hash_index' },
]

export function OpsJobsPage() {
  return (
    <RequireRole allow={['super_admin']}>
      <OpsPageChrome
        eyebrow="OPS · JOBS"
        title="Jobs"
        support="Static DROP job catalog — open filtered Runs for live attempts."
      >
        <div className="taste-panel overflow-hidden">
          <table className="taste-table">
            <thead>
              <tr>
                <th>Job</th>
                <th>Family</th>
                <th>Runs</th>
              </tr>
            </thead>
            <tbody>
              {CATALOG.map((row) => (
                <tr key={row.job}>
                  <td className="!py-2 text-ink">{row.label}</td>
                  <td className="!py-2">
                    <span className="taste-frost-chip !normal-case !tracking-normal">
                      {row.family}
                    </span>
                  </td>
                  <td className="!py-2">
                    <Link
                      to="/ops/runs"
                      search={opsRunsSearch({ job: row.job })}
                      className="text-xs text-habeas-mid hover:underline"
                    >
                      Filtered runs →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </OpsPageChrome>
    </RequireRole>
  )
}
