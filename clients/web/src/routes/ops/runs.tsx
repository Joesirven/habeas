import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'

import { opsRunsSearch } from '@/lib/ops-runs-search'
import type { ReactNode } from 'react'

import { RequireRole, OpsPageChrome } from '@/lib/auth'
import {
  listOpsRuns,
  type OpsRunJob,
  type OpsRunRecord,
  type OpsRunWindow,
} from '@/lib/api'

const FAIL_STATUSES = new Set(['submit_error', 'outcome_error', 'timeout', 'abandoned'])
const RUNNING_STATUSES = new Set(['claimed', 'in_flight'])
const WAITING_STATUSES = new Set(['pending'])

const STATUS_FILTERS = ['failed', 'in_progress', 'success'] as const
type StatusFilter = (typeof STATUS_FILTERS)[number]

const WINDOWS = ['8h', '24h', '1w'] as const satisfies readonly OpsRunWindow[]
const JOBS = ['connector', 'ingest', 'matching', 'hash_index'] as const satisfies readonly OpsRunJob[]

const JOB_LABELS: Record<OpsRunJob, string> = {
  connector: 'Connector',
  ingest: 'Ingest',
  matching: 'Matching',
  hash_index: 'Hash index',
}

const STATUS_TAB_LABELS: Record<'all' | StatusFilter, string> = {
  all: 'All',
  failed: 'Failed',
  in_progress: 'In progress',
  success: 'Success',
}

type RunsSearch = {
  status?: StatusFilter
  window?: OpsRunWindow
  job?: OpsRunJob
  request_id?: string
}

function formatDuration(seconds: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const rem = Math.round(seconds % 60)
  if (minutes < 60) return rem > 0 ? `${minutes}m ${rem}s` : `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remMin = minutes % 60
  return remMin > 0 ? `${hours}h ${remMin}m` : `${hours}h`
}

function formatStarted(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function StatusPill({ status }: { status: string }) {
  const failed = FAIL_STATUSES.has(status)
  const running = RUNNING_STATUSES.has(status)
  const waiting = WAITING_STATUSES.has(status)
  const success = status === 'success'

  let className =
    'inline-flex items-center rounded-sm border border-line px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-[0.08em] text-ink-soft'

  if (success) {
    className =
      'inline-flex items-center rounded-sm border border-emerald-600/25 bg-emerald-50 px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-[0.08em] text-emerald-800'
  } else if (failed) {
    className =
      'inline-flex items-center rounded-sm border border-red-600/25 bg-red-50 px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-[0.08em] text-red-800'
  } else if (running) {
    className =
      'inline-flex items-center rounded-sm border border-habeas-mid/35 bg-habeas-light/15 px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-[0.08em] text-habeas-navy animate-pulse'
  } else if (waiting) {
    className =
      'inline-flex items-center rounded-sm border border-habeas-mid/50 bg-transparent px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-[0.08em] text-habeas-mid'
  }

  return <span className={className}>{status.replaceAll('_', ' ')}</span>
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? 'taste-frost-chip border-habeas-mid/40 text-habeas-navy'
          : 'taste-frost-chip text-mute'
      }
      aria-pressed={active}
    >
      {children}
    </button>
  )
}

function RunIdLink({ run }: { run: OpsRunRecord }) {
  return (
    <Link
      to="/ops/runs/$job/$attemptId"
      params={{ job: run.job, attemptId: String(run.id) }}
      className="taste-link font-mono text-xs"
    >
      {run.job}-{run.id}
    </Link>
  )
}

export function OpsRunsPage() {
  const navigate = useNavigate({ from: '/ops/runs' })
  const search = useSearch({ from: '/ops/runs' })

  const statusTab: 'all' | StatusFilter = search.status ?? 'all'
  const windowFilter = search.window
  const jobFilter = search.job
  const requestId = search.request_id

  function patchSearch(patch: {
    status?: StatusFilter | null
    window?: OpsRunWindow | null
    job?: OpsRunJob | null
    request_id?: string | null
  }) {
    const next: RunsSearch = {
      status: 'status' in patch ? (patch.status ?? undefined) : search.status,
      window: 'window' in patch ? (patch.window ?? undefined) : search.window,
      job: 'job' in patch ? (patch.job ?? undefined) : search.job,
      request_id: 'request_id' in patch ? (patch.request_id ?? undefined) : search.request_id,
    }
    void navigate({ search: opsRunsSearch(next) })
  }

  const runsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'runs', search],
    queryFn: () =>
      listOpsRuns({
        status: search.status,
        job: search.job,
        request_id: search.request_id,
        window: search.window,
        limit: 100,
      }),
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const runs = runsQuery.data?.runs ?? []

  return (
    <RequireRole allow={['super_admin']}>
      <OpsPageChrome
        eyebrow="OPS · RUNS"
        title="Runs"
        support="Unified job attempts across connector, ingest, matching, and hash-index families."
      >
        <div className="taste-panel p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-2">
            <FilterChip active={statusTab === 'all'} onClick={() => patchSearch({ status: null })}>
              {STATUS_TAB_LABELS.all}
            </FilterChip>
            {STATUS_FILTERS.map((status) => (
              <FilterChip
                key={status}
                active={statusTab === status}
                onClick={() => patchSearch({ status })}
              >
                {STATUS_TAB_LABELS[status]}
              </FilterChip>
            ))}
            <span className="mx-1 hidden h-4 w-px bg-line sm:inline-block" aria-hidden />
            {WINDOWS.map((window) => (
              <FilterChip
                key={window}
                active={windowFilter === window}
                onClick={() =>
                  patchSearch({ window: windowFilter === window ? null : window })
                }
              >
                {window}
              </FilterChip>
            ))}
            <label className="ml-auto flex items-center gap-2 text-[0.65rem] font-medium uppercase tracking-[0.12em] text-mute">
              Job
              <select
                className="rounded-sm border border-line bg-paper-raised px-2 py-1 text-xs font-normal normal-case tracking-normal text-ink"
                value={jobFilter ?? ''}
                onChange={(event) => {
                  const value = event.target.value
                  patchSearch({ job: value ? (value as OpsRunJob) : null })
                }}
              >
                <option value="">All jobs</option>
                {JOBS.map((job) => (
                  <option key={job} value={job}>
                    {JOB_LABELS[job]}
                  </option>
                ))}
              </select>
            </label>
            {runsQuery.isFetching && !runsQuery.isPending ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>

          {requestId ? (
            <p className="mt-3 text-xs text-ink-soft">
              Filtered to request <span className="font-mono text-ink">{requestId}</span>
              {' · '}
              <button
                type="button"
                className="taste-link"
                onClick={() => patchSearch({ request_id: null })}
              >
                Clear
              </button>
            </p>
          ) : null}

          <div className="mt-4 overflow-x-auto">
            <table className="taste-table text-xs">
              <thead>
                <tr>
                  <th className="!py-2">Run id</th>
                  <th className="!py-2">Status</th>
                  <th className="!py-2">Job</th>
                  <th className="!py-2">Request</th>
                  <th className="!py-2">Started</th>
                  <th className="!py-2">Duration</th>
                  <th className="!py-2">Error</th>
                </tr>
              </thead>
              <tbody>
                {runsQuery.isPending ? (
                  <tr>
                    <td colSpan={7} className="!py-8 text-center text-ink-soft">
                      Loading runs…
                    </td>
                  </tr>
                ) : null}
                {runsQuery.isError ? (
                  <tr>
                    <td colSpan={7} className="!py-8 text-center text-red-700">
                      Could not load runs. Confirm admin-api and super_admin session.
                    </td>
                  </tr>
                ) : null}
                {runsQuery.isSuccess && runs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="!py-8 text-center text-ink-soft">
                      No runs for these filters.
                    </td>
                  </tr>
                ) : null}
                {runs.map((run) => (
                  <tr key={`${run.job}-${run.id}`}>
                    <td className="!py-2">
                      <RunIdLink run={run} />
                    </td>
                    <td className="!py-2">
                      <StatusPill status={run.status} />
                    </td>
                    <td className="!py-2 text-ink">
                      <span className="taste-frost-chip !px-1.5 !py-0.5 !normal-case !tracking-normal">
                        {JOB_LABELS[run.job] ?? run.job}
                      </span>
                    </td>
                    <td className="!py-2 font-mono text-[0.7rem] text-ink-soft">
                      {run.request_id ?? '—'}
                    </td>
                    <td className="!py-2 tabular-nums text-ink-soft">
                      {formatStarted(run.attempted_at)}
                    </td>
                    <td className="!py-2 tabular-nums text-ink-soft">
                      {formatDuration(run.duration_seconds)}
                    </td>
                    <td className="!py-2">
                      {run.has_error ? (
                        <span className="inline-flex items-center rounded-sm border border-red-600/20 bg-red-50 px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-[0.08em] text-red-800">
                          has_error
                        </span>
                      ) : (
                        <span className="text-mute">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </OpsPageChrome>
    </RequireRole>
  )
}
