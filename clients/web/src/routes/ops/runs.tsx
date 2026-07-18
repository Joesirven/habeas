import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { listRuns, type OpsTimeWindow, type RunSummary } from '@/lib/api'
import { RoleGate } from '@/lib/auth'
import {
  DEFAULT_RUNS_WINDOW,
  RUNS_JOB_FILTERS,
  RUNS_WINDOWS,
  type RunsJobFilter,
  type RunsSearch,
  type RunsStatusFilter,
  type RunsWindow,
} from '@/router'

const JOB_OPTIONS: { value: RunsJobFilter | ''; label: string }[] = [
  { value: '', label: 'All jobs' },
  { value: 'drop_connector', label: 'Download' },
  { value: 'drop_ingestor', label: 'Ingest' },
  { value: 'matching', label: 'Matching' },
  { value: 'hash_index_refresh', label: 'Hash index refresh' },
]

const STATUS_TABS: {
  key: 'all' | RunsStatusFilter
  label: string
  apiStatus?: RunsStatusFilter
}[] = [
  { key: 'all', label: 'All' },
  { key: 'failed', label: 'Failed', apiStatus: 'failed' },
  { key: 'in_flight', label: 'In progress', apiStatus: 'in_flight' },
  { key: 'success', label: 'Success', apiStatus: 'success' },
]

const JOB_LABELS: Record<RunsJobFilter, string> = {
  drop_connector: 'Download',
  drop_ingestor: 'Ingest',
  matching: 'Matching',
  hash_index_refresh: 'Hash index',
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function jobLabel(job: string): string {
  if (job in JOB_LABELS) return JOB_LABELS[job as RunsJobFilter]
  return job.replaceAll('_', ' ')
}

function isFailedStatus(status: string): boolean {
  const normalized = status.toLowerCase()
  return (
    normalized.includes('fail') ||
    normalized.includes('error') ||
    normalized === 'failed_terminal' ||
    normalized === 'abandoned' ||
    normalized === 'timeout'
  )
}

function isSuccessStatus(status: string): boolean {
  const normalized = status.toLowerCase()
  return (
    normalized.includes('success') ||
    normalized.includes('complete') ||
    normalized === 'ok' ||
    normalized === 'succeeded'
  )
}

function isInFlightStatus(status: string): boolean {
  const normalized = status.toLowerCase()
  return (
    normalized.includes('claimed') ||
    normalized === 'running' ||
    normalized === 'in_flight' ||
    normalized.includes('pending')
  )
}

function statusPillClass(status: string): string {
  if (isFailedStatus(status)) {
    return 'border-red-200/80 bg-red-50 text-red-800'
  }
  if (isSuccessStatus(status)) {
    return 'border-emerald-200/80 bg-emerald-50 text-emerald-800'
  }
  if (isInFlightStatus(status)) {
    return 'border-habeas-light/40 bg-habeas-mid/10 text-habeas-navy'
  }
  return 'border-line bg-panel/60 text-ink-soft'
}

function statusDotClass(status: string): string {
  if (isFailedStatus(status)) return 'bg-red-600'
  if (isSuccessStatus(status)) return 'bg-emerald-600'
  if (isInFlightStatus(status)) return 'bg-habeas-light animate-pulse'
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
  return new Date(value).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function parseAttemptId(run: RunSummary): string {
  const parts = run.run_id.split(':')
  return parts.length > 1 ? parts[parts.length - 1]! : String(run.attempt_number)
}

function activeStatusTab(status: RunsStatusFilter | undefined): (typeof STATUS_TABS)[number]['key'] {
  if (!status) return 'all'
  return status
}

function buildRunsSearch(
  current: RunsSearch,
  patch: Partial<{
    status: RunsStatusFilter | undefined
    job: RunsJobFilter | undefined
    window: RunsWindow
    request_id: string | undefined
  }>,
): RunsSearch {
  const next: RunsSearch = {
    window: patch.window ?? current.window ?? DEFAULT_RUNS_WINDOW,
  }
  const job = patch.job !== undefined ? patch.job : current.job
  const status = patch.status !== undefined ? patch.status : current.status
  const requestId = patch.request_id !== undefined ? patch.request_id : current.request_id
  if (job) next.job = job
  if (status) next.status = status
  if (requestId) next.request_id = requestId
  return next
}

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[0.62rem] font-medium uppercase tracking-[0.08em] ${statusPillClass(status)}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDotClass(status)}`} aria-hidden />
      {status.replaceAll('_', ' ')}
    </span>
  )
}

function RunsToolbar({
  search,
  onSearchChange,
}: {
  search: RunsSearch
  onSearchChange: (next: RunsSearch) => void
}) {
  const activeTab = activeStatusTab(search.status)

  return (
    <div className="flex flex-col gap-3 border-b border-line pb-3">
      <div className="flex flex-wrap items-center gap-2">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={activeTab === tab.key ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
            onClick={() =>
              onSearchChange(buildRunsSearch(search, { status: tab.apiStatus }))
            }
          >
            {tab.label}
          </button>
        ))}
        <span className="mx-1 hidden h-4 w-px bg-line sm:inline" aria-hidden />
        {RUNS_WINDOWS.map((windowOption) => (
          <button
            key={windowOption}
            type="button"
            className={
              (search.window ?? DEFAULT_RUNS_WINDOW) === windowOption
                ? 'taste-btn-primary text-xs'
                : 'taste-btn text-xs'
            }
            onClick={() => onSearchChange(buildRunsSearch(search, { window: windowOption }))}
          >
            {windowOption}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-2">
          <span className="taste-micro">Job</span>
          <select
            className="glass rounded-lg px-2 py-1.5 text-xs text-ink"
            value={search.job ?? ''}
            onChange={(event) => {
              const value = event.target.value
              onSearchChange(
                buildRunsSearch(search, {
                  job: RUNS_JOB_FILTERS.includes(value as RunsJobFilter)
                    ? (value as RunsJobFilter)
                    : undefined,
                }),
              )
            }}
          >
            {JOB_OPTIONS.map((option) => (
              <option key={option.value || 'all'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {search.request_id ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="taste-micro">Request filter</span>
          <span className="taste-frost-chip font-mono normal-case tracking-normal">
            {search.request_id}
          </span>
          <button
            type="button"
            className="taste-btn text-xs"
            onClick={() => onSearchChange(buildRunsSearch(search, { request_id: undefined }))}
          >
            Clear
          </button>
        </div>
      ) : null}
    </div>
  )
}

function RunsTable({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) {
    return <p className="px-3 py-5 text-xs text-ink-soft">No runs in this window.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="taste-table text-xs [&_td]:px-3 [&_td]:py-2 [&_th]:px-3 [&_th]:py-2">
        <thead>
          <tr>
            <th>Run</th>
            <th>Status</th>
            <th>Job</th>
            <th>Request</th>
            <th>Started</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const attemptId = parseAttemptId(run)
            return (
              <tr key={run.run_id} className="hover:bg-panel/40">
                <td className="whitespace-nowrap font-mono text-[0.7rem]">
                  <Link
                    to="/ops/runs/$job/$attemptId"
                    params={{ job: run.job, attemptId }}
                    className="taste-link"
                  >
                    {run.run_id}
                  </Link>
                </td>
                <td>
                  <StatusPill status={run.status} />
                </td>
                <td className="whitespace-nowrap">
                  <span className="font-medium text-ink">{jobLabel(run.job)}</span>
                  <span className="ml-1.5 font-mono text-[0.62rem] text-mute">{run.step}</span>
                </td>
                <td>
                  {run.request_id ? (
                    <Link
                      to="/requests/$requestId"
                      params={{ requestId: run.request_id }}
                      className="taste-link font-mono text-[0.7rem]"
                    >
                      {run.request_id.slice(0, 8)}…
                    </Link>
                  ) : (
                    <span className="text-ink-soft">—</span>
                  )}
                </td>
                <td className="whitespace-nowrap tabular-nums text-ink-soft">
                  {formatTimestamp(run.started_at)}
                </td>
                <td className="whitespace-nowrap tabular-nums text-ink-soft">
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
  const navigate = useNavigate()
  const search = useSearch({ from: '/ops/runs' })
  const { job, status, request_id: requestId } = search
  const window = search.window ?? DEFAULT_RUNS_WINDOW

  const runsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'runs', { job, status, window, requestId }],
    queryFn: () =>
      listRuns({
        job,
        status,
        request_id: requestId,
        window: window as OpsTimeWindow,
        limit: 100,
      }),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  function updateSearch(next: RunsSearch) {
    void navigate({ to: '/ops/runs', search: next, replace: true })
  }

  const loading = runsQuery.isPending && !runsQuery.data

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Ops · Run</Micro>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">Runs</h2>
            {runsQuery.isFetching && !runsQuery.isPending ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-ink-soft">
            Job attempts across DROP workers — filter by status, job, and time window.
          </p>
        </div>
      </header>

      <div className="taste-panel overflow-hidden">
        <div className="border-b border-line px-3 pt-3">
          <RunsToolbar search={search} onSearchChange={updateSearch} />
        </div>
        {loading ? (
          <div className="p-4">
            <SkeletonLines lines={8} />
          </div>
        ) : null}
        {runsQuery.isError ? (
          <p className="px-3 py-5 text-xs text-red-700">Could not load runs.</p>
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
