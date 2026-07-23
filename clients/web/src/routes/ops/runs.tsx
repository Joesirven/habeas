import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { type FormEvent, type ReactNode, useState } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  listRuns,
  resolveRunsTimeParams,
  type OpsTimeWindow,
  type RunSummary,
} from '@/lib/api'
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
  { value: '', label: 'All workers' },
  { value: 'drop_connector', label: 'drop_connector · Download' },
  { value: 'drop_ingestor', label: 'drop_ingestor · Ingest' },
  { value: 'matching', label: 'matching' },
  { value: 'hash_index_refresh', label: 'hash_index_refresh' },
]

const STATUS_TABS: {
  key: 'all' | RunsStatusFilter
  label: string
  apiStatus?: RunsStatusFilter
}[] = [
  { key: 'all', label: 'All' },
  { key: 'failed', label: 'Failed', apiStatus: 'failed' },
  { key: 'pending', label: 'Queued', apiStatus: 'pending' },
  { key: 'in_flight', label: 'In flight', apiStatus: 'in_flight' },
  { key: 'claimed', label: 'Claimed', apiStatus: 'claimed' },
  { key: 'abandoned', label: 'Abandoned', apiStatus: 'abandoned' },
  { key: 'success', label: 'Finished', apiStatus: 'success' },
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

function statusPillVariant(status: string): 'ok' | 'fail' | 'run' | 'wait' {
  if (isFailedStatus(status)) return 'fail'
  if (isSuccessStatus(status)) return 'ok'
  if (isInFlightStatus(status)) return 'run'
  return 'wait'
}

function StatusPill({ status }: { status: string }) {
  const variant = statusPillVariant(status)
  return (
    <span className={`taste-status-pill taste-status-${variant}`}>
      <span className="taste-status-dot" aria-hidden />
      {status.replaceAll('_', ' ')}
    </span>
  )
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

function toDatetimeLocalValue(iso: string | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function fromDatetimeLocalValue(value: string): string | undefined {
  const trimmed = value.trim()
  if (!trimmed) return undefined
  const parsed = Date.parse(trimmed)
  if (Number.isNaN(parsed)) return undefined
  return new Date(parsed).toISOString()
}

function buildRunsSearch(
  current: RunsSearch,
  patch: Partial<{
    status: RunsStatusFilter | undefined
    job: RunsJobFilter | undefined
    window: RunsWindow
    request_id: string | undefined
    since: string | undefined
  }>,
): RunsSearch {
  const next: RunsSearch = {
    window: patch.window ?? current.window ?? DEFAULT_RUNS_WINDOW,
  }
  const job = patch.job !== undefined ? patch.job : current.job
  const status = patch.status !== undefined ? patch.status : current.status
  const requestId = patch.request_id !== undefined ? patch.request_id : current.request_id
  const since = patch.since !== undefined ? patch.since : current.since
  if (job) next.job = job
  if (status) next.status = status
  if (requestId) next.request_id = requestId
  if (next.window === 'custom' && since) next.since = since
  return next
}

function RunsToolbar({
  search,
  onSearchChange,
}: {
  search: RunsSearch
  onSearchChange: (next: RunsSearch) => void
}) {
  const activeTab = activeStatusTab(search.status)
  const [requestDraft, setRequestDraft] = useState(search.request_id ?? '')
  const window = search.window ?? DEFAULT_RUNS_WINDOW

  function applyRequestFilter(event: FormEvent) {
    event.preventDefault()
    const trimmed = requestDraft.trim()
    onSearchChange(
      buildRunsSearch(search, { request_id: trimmed ? trimmed : undefined }),
    )
  }

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
              window === windowOption ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'
            }
            onClick={() =>
              onSearchChange(
                buildRunsSearch(search, {
                  window: windowOption,
                  since:
                    windowOption === 'custom'
                      ? search.since ?? new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
                      : undefined,
                }),
              )
            }
          >
            {windowOption}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="taste-micro">Worker</span>
          <select
            className="glass min-w-[12rem] rounded-lg px-2 py-1.5 text-xs text-ink"
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

        <form className="flex flex-wrap items-end gap-2" onSubmit={applyRequestFilter}>
          <label className="flex flex-col gap-1">
            <span className="taste-micro">Request id</span>
            <input
              className="glass min-w-[14rem] rounded-lg px-2 py-1.5 font-mono text-xs text-ink"
              value={requestDraft}
              onChange={(event) => setRequestDraft(event.target.value)}
              placeholder="uuid…"
              aria-label="Filter by request id"
            />
          </label>
          <button type="submit" className="taste-btn text-xs">
            Apply
          </button>
          {search.request_id ? (
            <button
              type="button"
              className="taste-btn text-xs"
              onClick={() => {
                setRequestDraft('')
                onSearchChange(buildRunsSearch(search, { request_id: undefined }))
              }}
            >
              Clear
            </button>
          ) : null}
        </form>

        {window === 'custom' ? (
          <label className="flex flex-col gap-1">
            <span className="taste-micro">Since</span>
            <input
              type="datetime-local"
              className="glass rounded-lg px-2 py-1.5 text-xs text-ink"
              value={toDatetimeLocalValue(search.since)}
              onChange={(event) =>
                onSearchChange(
                  buildRunsSearch(search, {
                    window: 'custom',
                    since: fromDatetimeLocalValue(event.target.value),
                  }),
                )
              }
            />
          </label>
        ) : null}
      </div>
    </div>
  )
}

function RunsTable({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) {
    return <p className="px-3 py-5 text-xs text-ink-soft">No runs in this window.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="taste-table">
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
  const { job, status, request_id: requestId, since } = search
  const window = search.window ?? DEFAULT_RUNS_WINDOW

  const timeParams = resolveRunsTimeParams(window as OpsTimeWindow, since)
  const runsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'runs', { job, status, window, requestId, since, timeParams }],
    queryFn: () =>
      listRuns({
        job,
        status,
        request_id: requestId,
        ...timeParams,
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
    <section className="taste-ops-page">
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
            Job attempts across DROP workers — filter by status, worker, request, and time.
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
