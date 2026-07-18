import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { opsRunsSearch } from '@/lib/ops-runs-search'

import { RequireRole, OpsPageChrome } from '@/lib/auth'
import {
  getOpsRunDetail,
  type OpsRunJob,
  type OpsRunTimelineEvent,
} from '@/lib/api'

const JOB_LABELS: Record<OpsRunJob, string> = {
  connector: 'Connector',
  ingest: 'Ingest',
  matching: 'Matching',
  hash_index: 'Hash index',
}

const JOBS = new Set<string>(['connector', 'ingest', 'matching', 'hash_index'])

/** DROP console tab query — mirrors API console_href (no auto-mutate). */
const CONSOLE_TAB = {
  connector: 'download',
  ingest: 'ingest',
  matching: 'matching',
  hash_index: 'home',
} as const

function isOpsRunJob(value: string): value is OpsRunJob {
  return JOBS.has(value)
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
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

function timelineLabel(event: OpsRunTimelineEvent['event']): string {
  if (event === 'attempted') return 'Attempted'
  if (event === 'claimed') return 'Claimed'
  if (event === 'completed') return 'Completed'
  return event
}

export function OpsRunDetailPage({
  job,
  attemptId,
}: {
  job: string
  attemptId: string
}) {
  const jobValid = isOpsRunJob(job)
  const attemptNum = Number.parseInt(attemptId, 10)
  const idValid = Number.isFinite(attemptNum) && attemptNum >= 1

  const detailQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'runs', job, attemptId],
    queryFn: () => getOpsRunDetail(job, attemptNum),
    enabled: jobValid && idValid,
    retry: false,
  })

  const detail = detailQuery.data
  const jobLabel = jobValid ? JOB_LABELS[job] : job
  const consoleTab = jobValid ? CONSOLE_TAB[job] : 'home'

  return (
    <RequireRole allow={['super_admin']}>
      <OpsPageChrome
        eyebrow="OPS · RUN DETAIL"
        title={`${jobLabel} · #${attemptId}`}
        support="Timeline from attempt timestamps. Privileged redacted errors only — no filenames or storage URIs."
      >
        <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
          <Link
            to="/ops/runs" search={opsRunsSearch()}
            className="text-habeas-mid underline decoration-ink/20 underline-offset-4 hover:decoration-habeas-mid"
          >
            ← Runs
          </Link>
          {jobValid ? (
            <Link
              to="/ops/drop-pipeline"
              search={{ tab: consoleTab }}
              className="taste-frost-chip"
            >
              Open DROP console
            </Link>
          ) : null}
        </div>

        {!jobValid || !idValid ? (
          <div className="taste-panel p-5">
            <p className="text-sm text-ink-soft">Invalid run path — expected /ops/runs/&lt;job&gt;/&lt;attemptId&gt;.</p>
          </div>
        ) : null}

        {jobValid && idValid && detailQuery.isPending ? (
          <div className="taste-panel space-y-3 p-5" role="status" aria-label="Loading run">
            <div className="h-4 w-full animate-pulse rounded-md bg-line/80" aria-hidden />
            <div className="h-4 w-2/3 animate-pulse rounded-md bg-line/80" aria-hidden />
          </div>
        ) : null}

        {jobValid && idValid && detailQuery.isError ? (
          <div className="taste-panel p-5">
            <p className="text-sm text-red-700">
              {detailQuery.error instanceof Error
                ? detailQuery.error.message
                : 'Could not load run detail.'}
            </p>
          </div>
        ) : null}

        {detail ? (
          <div className="space-y-5">
            <div className="taste-panel overflow-x-auto p-5">
              <table className="taste-table">
                <tbody>
                  <tr>
                    <th className="w-40">Status</th>
                    <td className="font-medium uppercase tracking-[0.06em]">{detail.status}</td>
                  </tr>
                  <tr>
                    <th>Job</th>
                    <td>{JOB_LABELS[detail.job] ?? detail.job}</td>
                  </tr>
                  <tr>
                    <th>Attempt id</th>
                    <td className="tabular-nums">{detail.id}</td>
                  </tr>
                  <tr>
                    <th>Request</th>
                    <td className="tabular-nums">{detail.request_id ?? '—'}</td>
                  </tr>
                  <tr>
                    <th>Duration</th>
                    <td className="tabular-nums">{formatDuration(detail.duration_seconds)}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="taste-panel p-5">
              <p className="taste-micro">Timeline</p>
              {detail.timeline.length === 0 ? (
                <p className="mt-3 text-sm text-ink-soft">No timestamps on this attempt.</p>
              ) : (
                <ol className="mt-4 space-y-3 border-l border-line pl-4">
                  {detail.timeline.map((step) => (
                    <li key={`${step.event}-${step.at}`} className="relative">
                      <span
                        className="absolute -left-[1.15rem] top-1.5 size-2 rounded-full bg-habeas-mid"
                        aria-hidden
                      />
                      <p className="text-sm font-medium text-ink">{timelineLabel(step.event)}</p>
                      <p className="text-xs tabular-nums text-ink-soft">{formatWhen(step.at)}</p>
                    </li>
                  ))}
                </ol>
              )}
              {detail.claimed_at == null ? (
                <p className="mt-4 text-xs text-ink-soft">
                  Claimed time is not stored on attempt rows — only attempted / completed when present.
                </p>
              ) : null}
            </div>

            <div className="taste-panel p-5">
              <p className="taste-micro">Privileged error</p>
              {!detail.has_error || !detail.error_redacted ? (
                <p className="mt-3 text-sm text-ink-soft">No error on this attempt.</p>
              ) : (
                <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-line/20 p-3 text-xs leading-relaxed text-ink">
                  {detail.error_redacted}
                </pre>
              )}
            </div>
          </div>
        ) : null}
      </OpsPageChrome>
    </RequireRole>
  )
}
