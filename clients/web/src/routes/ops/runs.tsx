import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { listRuns, type OpsTimeWindow, type RunSummary } from '@/lib/api'
import { RoleGate } from '@/lib/auth'

const JOB_OPTIONS = [
  { value: '', label: 'All jobs' },
  { value: 'drop_connector', label: 'Download' },
  { value: 'drop_ingestor', label: 'Ingest' },
  { value: 'matching', label: 'Matching' },
  { value: 'hash_index_refresh', label: 'Hash index refresh' },
] as const

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'failed', label: 'Failed (terminal)' },
  { value: 'success', label: 'Success' },
  { value: 'claimed', label: 'Claimed' },
  { value: 'in_flight', label: 'In flight' },
] as const

const WINDOW_OPTIONS: { value: OpsTimeWindow; label: string }[] = [
  { value: '8h', label: '8h' },
  { value: '24h', label: '24h' },
  { value: '1w', label: '1w' },
]

const JOB_LABELS: Record<string, string> = {
  drop_connector: 'Download',
  drop_ingestor: 'Ingest',
  matching: 'Matching',
  hash_index_refresh: 'Hash index',
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function jobLabel(job: string): string {
  return JOB_LABELS[job] ?? job.replaceAll('_', ' ')
}

function runStatusClass(status: string): string {
  const normalized = status.toLowerCase()
  if (
    normalized.includes('fail') ||
    normalized.includes('error') ||
    normalized === 'failed_terminal' ||
    normalized === 'abandoned' ||
    normalized === 'timeout'
  ) {
    return 'text-red-700'
  }
  if (
    normalized.includes('success') ||
    normalized.includes('complete') ||
    normalized === 'ok' ||
    normalized === 'succeeded'
  ) {
    return 'text-emerald-700'
  }
  if (normalized.includes('pending') || normalized.includes('claimed') || normalized === 'running') {
    return 'text-habeas-mid'
  }
  return 'text-ink-soft'
}

function runStatusDotClass(status: string): string {
  const normalized = status.toLowerCase()
  if (
    normalized.includes('fail') ||
    normalized.includes('error') ||
    normalized === 'failed_terminal' ||
    normalized === 'abandoned' ||
    normalized === 'timeout'
  ) {
    return 'bg-red-600'
  }
  if (
    normalized.includes('success') ||
    normalized.includes('complete') ||
    normalized === 'ok' ||
    normalized === 'succeeded'
  ) {
    return 'bg-emerald-600'
  }
  if (normalized.includes('claimed') || normalized === 'running' || normalized === 'in_flight') {
    return 'bg-habeas-light animate-pulse'
  }
  return 'bg-line-strong'
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.round(seconds % 60)
  if (minutes < 60) return remainder > 0 ? `${minutes}m ${remainder}s` : `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function parseAttemptId(run: RunSummary): string {
  const parts = run.run_id.split(':')
  return parts.length > 1 ? parts[parts.length - 1]! : String(run.attempt_number)
}

function RunsFilters({
  job,
  status,
  window,
  onJobChange,
  onStatusChange,
  onWindowChange,
}: {
  job: string
  status: string
  window: OpsTimeWindow
  onJobChange: (value: string) => void
  onStatusChange: (value: string) => void
  onWindowChange: (value: OpsTimeWindow) => void
}) {
  return (
    <div className="flex flex-wrap items-end gap-4">
      <label className="flex flex-col gap-1.5">
        <span className="taste-micro">Window</span>
        <div className="flex gap-1">
          {WINDOW_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={window === option.value ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
              onClick={() => onWindowChange(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="taste-micro">Job</span>
        <select
          className="glass rounded-lg px-3 py-2 text-sm text-ink"
          value={job}
          onChange={(event) => onJobChange(event.target.value)}
        >
          {JOB_OPTIONS.map((option) => (
            <option key={option.value || 'all'} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="taste-micro">Status</span>
        <select
          className="glass rounded-lg px-3 py-2 text-sm text-ink"
          value={status}
          onChange={(event) => onStatusChange(event.target.value)}
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value || 'all'} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}

function RunsTable({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) {
    return <p className="p-6 text-sm text-ink-soft">No runs in this window.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="taste-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Status</th>
            <th>Job</th>
            <th>Request</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const attemptId = parseAttemptId(run)
            return (
              <tr key={run.run_id}>
                <td className="whitespace-nowrap tabular-nums text-ink-soft">
                  <Link
                    to="/ops/runs/$job/$attemptId"
                    params={{ job: run.job, attemptId }}
                    className="taste-link"
                  >
                    {formatTimestamp(run.started_at)}
                  </Link>
                </td>
                <td>
                  <span className="inline-flex items-center gap-2">
                    <span
                      className={`h-2 w-2 shrink-0 rounded-full ${runStatusDotClass(run.status)}`}
                      aria-hidden="true"
                    />
                    <span className={`text-xs font-medium ${runStatusClass(run.status)}`}>
                      {run.status}
                    </span>
                  </span>
                </td>
                <td>
                  <span className="taste-frost-chip text-xs">{jobLabel(run.job)}</span>
                  <span className="ml-2 font-mono text-[0.65rem] text-mute">{run.step}</span>
                </td>
                <td>
                  {run.request_id ? (
                    <Link
                      to="/requests/$requestId"
                      params={{ requestId: run.request_id }}
                      className="taste-link font-mono text-xs"
                    >
                      {run.request_id}
                    </Link>
                  ) : (
                    <span className="text-ink-soft">—</span>
                  )}
                </td>
                <td className="tabular-nums text-ink-soft">
                  {formatDuration(run.duration_seconds)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function RunsContent() {
  const [job, setJob] = useState('')
  const [status, setStatus] = useState('')
  const [window, setWindow] = useState<OpsTimeWindow>('24h')

  const runsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'runs', { job, status, window }],
    queryFn: () =>
      listRuns({
        job: job || undefined,
        status: status || undefined,
        window,
        limit: 100,
      }),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const loading = runsQuery.isPending && !runsQuery.data

  return (
    <section className="space-y-10">
      <header className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
        <div>
          <Micro>Ops · Run</Micro>
          <div className="mt-3 flex flex-wrap items-baseline gap-3">
            <h2 className="font-display text-[2.5rem] font-medium leading-none tracking-tight text-ink">
              Runs
            </h2>
            {runsQuery.isFetching && !runsQuery.isPending ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>
          <p className="mt-3 max-w-md text-sm text-ink-soft">
            Job attempts across DROP workers — ids, statuses, and durations only.
          </p>
        </div>
        <RunsFilters
          job={job}
          status={status}
          window={window}
          onJobChange={setJob}
          onStatusChange={setStatus}
          onWindowChange={setWindow}
        />
      </header>

      <div className="taste-panel overflow-hidden">
        {loading ? (
          <div className="p-6">
            <SkeletonLines lines={8} />
          </div>
        ) : null}
        {runsQuery.isError ? (
          <p className="p-6 text-sm text-red-700">Could not load runs.</p>
        ) : null}
        {!loading && !runsQuery.isError && runsQuery.data ? (
          <RunsTable runs={runsQuery.data} />
        ) : null}
      </div>
    </section>
  )
}

export function OpsRunsPage() {
  return (
    <RoleGate allow={(role) => role === 'super_admin'}>
      <RunsContent />
    </RoleGate>
  )
}
