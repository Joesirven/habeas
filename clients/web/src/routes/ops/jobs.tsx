import { Link } from '@tanstack/react-router'

import { RoleGate } from '@/lib/auth'
import type { RunsJobFilter } from '@/router'

const JOB_CATALOG: {
  key: RunsJobFilter
  label: string
  step: string
}[] = [
  { key: 'drop_connector', label: 'Download', step: 'drop_connector' },
  { key: 'drop_ingestor', label: 'Ingest', step: 'drop_ingestor' },
  { key: 'matching', label: 'Matching', step: 'matching' },
  { key: 'hash_index_refresh', label: 'Hash index refresh', step: 'hash_index_refresh' },
]

function Micro({ children }: { children: React.ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function JobsContent() {
  return (
    <section className="space-y-4">
      <header>
        <Micro>Ops · Job</Micro>
        <h2 className="mt-1 font-display text-xl font-medium tracking-tight text-ink">Jobs</h2>
        <p className="mt-1 text-xs text-ink-soft">
          Static DROP worker catalog — open filtered Runs for each job.
        </p>
      </header>

      <div className="taste-panel overflow-hidden">
        <div className="overflow-x-auto">
          <table className="taste-table text-xs [&_td]:px-3 [&_td]:py-2 [&_th]:px-3 [&_th]:py-2">
            <thead>
              <tr>
                <th>Job</th>
                <th>Worker key</th>
                <th>Runs</th>
              </tr>
            </thead>
            <tbody>
              {JOB_CATALOG.map((job) => (
                <tr key={job.key} className="hover:bg-panel/40">
                  <td className="font-medium text-ink">{job.label}</td>
                  <td className="font-mono text-[0.7rem] text-ink-soft">{job.step}</td>
                  <td>
                    <Link
                      to="/ops/runs"
                      search={{ job: job.key, window: '24h' }}
                      className="taste-link text-xs"
                    >
                      View runs →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}

export function OpsJobsPage() {
  return (
    <RoleGate allow={(role) => role === 'super_admin'}>
      <JobsContent />
    </RoleGate>
  )
}
