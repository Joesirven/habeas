import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { RunTimeline } from '@/components/ops/RunTimeline'
import { Badge } from '@/components/ui/badge'
import { actionToast } from '@/lib/action-toast'
import { getRunDetail, type RunDetail, type RunEvent } from '@/lib/api'
import { ForbiddenState, useMe } from '@/lib/auth'
import { runsSearchForWorker, type PipelineSearch } from '@/router'

type DetailTab = 'overview' | 'timeline' | 'output' | 'events'

const JOB_LABELS: Record<string, string> = {
  drop_connector: 'Download',
  drop_ingestor: 'Ingest',
  drop_ingest: 'Ingest',
  matching: 'Matching',
  hash_index_refresh: 'Hash index refresh',
}

const CONSOLE_SEARCH_BY_JOB: Record<string, PipelineSearch> = {
  drop_connector: { tab: 'pipeline', stage: 'download' },
  drop_ingestor: { tab: 'pipeline', stage: 'ingest' },
  drop_ingest: { tab: 'pipeline', stage: 'ingest' },
  matching: { tab: 'pipeline', stage: 'matching' },
  hash_index_refresh: { tab: 'hash_refresh' },
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function jobLabel(job: string): string {
  return JOB_LABELS[job] ?? job.replaceAll('_', ' ')
}

function runStatusVariant(status: string): 'ok' | 'fail' | 'run' | 'wait' | 'default' {
  const normalized = status.toLowerCase()
  if (
    normalized.includes('fail') ||
    normalized.includes('error') ||
    normalized === 'failed_terminal' ||
    normalized === 'abandoned' ||
    normalized === 'timeout'
  ) {
    return 'fail'
  }
  if (
    normalized.includes('success') ||
    normalized.includes('complete') ||
    normalized === 'ok' ||
    normalized === 'succeeded'
  ) {
    return 'ok'
  }
  if (normalized.includes('pending') || normalized.includes('claimed') || normalized === 'running') {
    return 'run'
  }
  return 'wait'
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

function durationLabelFromRange(
  startAt: string | null | undefined,
  endAt?: string | null,
): string | null {
  if (!startAt) return null
  const start = new Date(startAt).getTime()
  if (Number.isNaN(start)) return null
  const end = endAt ? new Date(endAt).getTime() : Date.now()
  if (Number.isNaN(end) || end < start) return null
  return formatDuration((end - start) / 1000)
}

/** Best-effort bulk process timestamps from run detail raw payload (no invented fields). */
function bulkDurationFromRaw(raw: Record<string, unknown> | undefined): string | null {
  if (!raw) return null
  const process =
    (raw.process as Record<string, unknown> | undefined) ??
    (raw.bulk_process as Record<string, unknown> | undefined) ??
    null
  const processAt =
    (typeof raw.process_at === 'string' ? raw.process_at : null) ??
    (typeof process?.process_at === 'string' ? process.process_at : null) ??
    (typeof raw.bulk_process_at === 'string' ? raw.bulk_process_at : null)
  const completedAt =
    (typeof raw.process_completed_at === 'string' ? raw.process_completed_at : null) ??
    (typeof process?.completed_at === 'string' ? process.completed_at : null) ??
    (typeof raw.bulk_completed_at === 'string' ? raw.bulk_completed_at : null)
  return durationLabelFromRange(processAt, completedAt)
}

function MiniDurationRing({
  percent,
  tone = 'navy',
}: {
  percent: number
  tone?: 'navy' | 'emerald'
}) {
  const clamped = Math.max(0, Math.min(100, percent))
  const color = tone === 'emerald' ? 'stroke-emerald-600' : 'stroke-habeas-navy'
  const r = 14
  const c = 2 * Math.PI * r
  const offset = c - (clamped / 100) * c
  return (
    <svg viewBox="0 0 36 36" className="h-9 w-9 shrink-0" aria-hidden="true">
      <circle cx="18" cy="18" r={r} fill="none" className="stroke-line" strokeWidth="3" />
      <circle
        cx="18"
        cy="18"
        r={r}
        fill="none"
        className={color}
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={offset}
        transform="rotate(-90 18 18)"
      />
    </svg>
  )
}

function DurationVizCard({
  label,
  value,
  running,
}: {
  label: string
  value: string
  running?: boolean
}) {
  const known = value !== '—'
  return (
    <div className="flex min-w-[7rem] items-center gap-2 rounded-lg border border-line/80 bg-paper/60 px-3 py-2.5">
      {known ? (
        <MiniDurationRing percent={running ? 55 : 100} tone={running ? 'emerald' : 'navy'} />
      ) : (
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-dashed border-line text-[0.55rem] text-mute"
          aria-hidden="true"
        >
          —
        </div>
      )}
      <div className="min-w-0">
        <p className="taste-micro">{label}</p>
        <p className="mt-0.5 text-sm font-semibold tabular-nums text-ink">
          {value}
          {known && running ? '…' : ''}
        </p>
      </div>
    </div>
  )
}

function Metric({ label, value, mono = false }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2.5">
      <dt className="taste-micro">{label}</dt>
      <dd className={`mt-1 text-sm ${mono ? 'font-mono text-xs break-all' : 'tabular-nums'}`}>
        {value}
      </dd>
    </div>
  )
}

function RunDetailHeader({ detail }: { detail: RunDetail }) {
  const consoleSearch = CONSOLE_SEARCH_BY_JOB[detail.job]

  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/ops/runs" className="taste-link text-xs">
          ← Runs
        </Link>
        <Link
          to="/ops/runs"
          search={runsSearchForWorker(detail.job)}
          className="taste-frost-chip"
        >
          {jobLabel(detail.job)}
        </Link>
        <Badge variant={runStatusVariant(detail.status)}>{detail.status}</Badge>
      </div>
      <div>
        <Micro>Run detail</Micro>
        <h2 className="mt-1 font-display text-xl font-medium tracking-tight text-ink sm:text-2xl">
          Attempt #{detail.attempt_id}
        </h2>
        <p className="mt-2 text-sm text-ink-soft">
          Run <span className="font-mono text-xs">{detail.run_id}</span>
          {detail.request_id ? (
            <>
              {' '}
              · Request{' '}
              <Link
                to="/requests/$requestId"
                params={{ requestId: detail.request_id }}
                className="taste-link font-mono text-xs"
              >
                {detail.request_id}
              </Link>
            </>
          ) : (
            ' · No request (batch job)'
          )}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {consoleSearch ? (
          <Link to="/" search={consoleSearch} className="taste-btn text-xs">
            Dashboard · {jobLabel(detail.job)}
          </Link>
        ) : null}
        <Link
          to="/ops/runs"
          search={runsSearchForWorker(detail.job)}
          className="taste-btn text-xs"
        >
          Worker runs →
        </Link>
      </div>
    </header>
  )
}

function HashIndexRunPanel({ detail }: { detail: RunDetail }) {
  const metrics = detail.hash_index_run
  if (detail.job !== 'hash_index_refresh') return null

  return (
    <div className="rounded-md border border-line bg-paper p-4">
      <Micro>dbt pipeline outcome</Micro>
      <p className="mt-1 text-xs text-ink-soft">
        Rows written to serving marts and rematch enqueue count from hash_index_refresh_runs.
      </p>
      {!metrics ? (
        <p className="mt-3 text-xs text-mute">No dbt run row linked to this attempt yet.</p>
      ) : (
        <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric
            label="Run status"
            value={
              metrics.run_status ? (
                <Badge variant={runStatusVariant(metrics.run_status)}>{metrics.run_status}</Badge>
              ) : (
                '—'
              )
            }
          />
          <Metric label="Rows email" value={metrics.rows_email ?? '—'} />
          <Metric label="Rows phone" value={metrics.rows_phone ?? '—'} />
          <Metric label="Rows NDZ" value={metrics.rows_ndz ?? '—'} />
          <Metric label="Rematch enqueued" value={metrics.rematch_enqueued_count ?? '—'} />
          <Metric label="Run started" value={formatTimestamp(metrics.run_started_at)} />
          <Metric label="Run finished" value={formatTimestamp(metrics.run_finished_at)} />
          {metrics.run_error_message ? (
            <Metric label="Run error" value={metrics.run_error_message} />
          ) : null}
        </dl>
      )}
    </div>
  )
}

function OverviewPanel({ detail }: { detail: RunDetail }) {
  const stageRunning = !detail.completed_at && Boolean(detail.started_at)
  const stageDuration =
    formatDuration(detail.duration_seconds) !== '—'
      ? formatDuration(detail.duration_seconds)
      : durationLabelFromRange(detail.started_at, detail.completed_at) ?? '—'
  const bulkDuration = bulkDurationFromRaw(detail.raw) ?? '—'

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <DurationVizCard
          label="Stage duration"
          value={stageDuration}
          running={stageRunning}
        />
        <DurationVizCard label="Bulk run duration" value={bulkDuration} />
      </div>
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Metric label="Job" value={jobLabel(detail.job)} />
        <Metric label="Step" value={detail.step ?? '—'} mono />
        <Metric label="Status" value={<Badge variant={runStatusVariant(detail.status)}>{detail.status}</Badge>} />
        <Metric label="Attempt #" value={detail.attempt_number ?? detail.attempt_id} />
        <Metric label="Worker id" value={detail.worker_id ?? '—'} mono />
        <Metric label="Duration" value={formatDuration(detail.duration_seconds)} />
        <Metric label="Started" value={formatTimestamp(detail.started_at)} />
        <Metric label="Submitted" value={formatTimestamp(detail.submitted_at)} />
        <Metric label="Completed" value={formatTimestamp(detail.completed_at)} />
        {detail.state ? <Metric label="State" value={detail.state} mono /> : null}
        {detail.list_types && detail.list_types.length > 0 ? (
          <Metric
            label="List types"
            value={detail.list_types.join(', ')}
            mono
          />
        ) : null}
        {detail.request_id ? (
          <Metric
            label="Request"
            value={
              <Link
                to="/requests/$requestId"
                params={{ requestId: detail.request_id }}
                className="taste-link font-mono text-xs"
              >
                {detail.request_id}
              </Link>
            }
          />
        ) : null}
        <Metric label="Run id" value={detail.run_id} mono />
      </dl>
      <HashIndexRunPanel detail={detail} />
    </div>
  )
}

function OutputPanel({ detail, isSuperAdmin }: { detail: RunDetail; isSuperAdmin: boolean }) {
  const hasError = Boolean(detail.error_message || detail.error_code)
  const rawJson = JSON.stringify(detail.raw ?? detail, null, 2)

  const handleCopyJson = () => {
    void navigator.clipboard.writeText(rawJson).then(() => {
      actionToast.copied('Copied run JSON', handleCopyJson)
    })
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2.5">
          <p className="taste-micro">Error code</p>
          <p className="mt-1 font-mono text-sm">{detail.error_code ?? '—'}</p>
        </div>
        <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2.5">
          <p className="taste-micro">Outcome</p>
          <p className="mt-1 text-sm">
            <Badge variant={runStatusVariant(detail.status)}>{detail.status}</Badge>
          </p>
        </div>
      </div>

      <div
        className={`rounded-lg border p-4 ${
          hasError ? 'border-red-200/80 bg-red-50/40' : 'border-line/80 bg-paper/60'
        }`}
      >
        <p className="taste-micro">
          {isSuperAdmin ? 'Error message (redacted)' : 'Error message'}
        </p>
        <pre className="mt-2 whitespace-pre-wrap break-words font-mono text-xs text-ink-soft">
          {hasError ? detail.error_message ?? '—' : 'No error message on record.'}
        </pre>
        <p className="mt-2 text-[0.65rem] text-mute">
          Stdout/stderr are not persisted in v1 — attempt row fields and audit events only.
        </p>
      </div>

      <div className="rounded-lg border border-line/80 bg-paper/60 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="taste-micro">Attempt payload (API)</p>
          <button
            type="button"
            className="taste-btn text-[0.65rem]"
            onClick={handleCopyJson}
          >
            Copy JSON
          </button>
        </div>
        <pre className="mt-3 max-h-[28rem] overflow-auto whitespace-pre-wrap break-words font-mono text-[0.65rem] text-ink-soft">
          {rawJson}
        </pre>
      </div>
    </div>
  )
}

function RunEventsTable({ events }: { events: RunEvent[] }) {
  if (events.length === 0) {
    return <p className="text-sm text-ink-soft">No audit events recorded for this run.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="taste-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Event</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.id}>
              <td className="whitespace-nowrap tabular-nums text-ink-soft">
                {formatTimestamp(event.occurred_at)}
              </td>
              <td className="font-mono text-xs">{event.event_type}</td>
              <td className="text-ink-soft">{event.summary ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RunDetailTabs({
  tab,
  onTabChange,
  detail,
  isSuperAdmin,
}: {
  tab: DetailTab
  onTabChange: (tab: DetailTab) => void
  detail: RunDetail
  isSuperAdmin: boolean
}) {
  const tabs: { id: DetailTab; label: string; count?: number }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'timeline', label: 'Timeline', count: detail.timeline.length },
    { id: 'output', label: 'Output' },
    { id: 'events', label: 'Events', count: detail.events.length },
  ]

  return (
    <div className="taste-panel overflow-hidden">
      <div className="flex flex-wrap gap-0 border-b border-line px-2">
        {tabs.map((item) => {
          const selected = tab === item.id
          return (
            <button
              key={item.id}
              type="button"
              className={
                selected
                  ? 'relative px-3.5 py-2.5 text-xs font-medium text-habeas-navy after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:rounded-full after:bg-habeas-navy'
                  : 'px-3.5 py-2.5 text-xs font-medium text-mute transition-colors hover:text-ink'
              }
              onClick={() => onTabChange(item.id)}
            >
              {item.label}
              {item.count != null && item.count > 0 ? (
                <span className="ml-1.5 tabular-nums text-[0.65rem] opacity-70">
                  ({item.count})
                </span>
              ) : null}
            </button>
          )
        })}
      </div>
      <div className="p-4 sm:p-5">
        {tab === 'overview' ? <OverviewPanel detail={detail} /> : null}
        {tab === 'timeline' ? (
          <RunTimeline steps={detail.timeline} emptyMessage="No timeline events on this attempt." />
        ) : null}
        {tab === 'output' ? <OutputPanel detail={detail} isSuperAdmin={isSuperAdmin} /> : null}
        {tab === 'events' ? <RunEventsTable events={detail.events} /> : null}
      </div>
    </div>
  )
}

function RunForbiddenState() {
  return (
    <div className="taste-panel p-8">
      <ForbiddenState />
    </div>
  )
}

export function RunDetailPage() {
  const { job, attemptId } = useParams({ strict: false }) as {
    job?: string
    attemptId?: string
  }
  const parsedAttemptId = attemptId ? Number.parseInt(attemptId, 10) : Number.NaN
  const [tab, setTab] = useState<DetailTab>('overview')
  const { isSuperAdmin, isLoading: meLoading } = useMe()

  const detailQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'runs', job, parsedAttemptId],
    queryFn: () => getRunDetail(job!, parsedAttemptId),
    enabled: Boolean(job) && Number.isFinite(parsedAttemptId) && parsedAttemptId > 0,
    retry: (failureCount, error) => {
      if (error instanceof Error && error.message.includes('403')) return false
      return failureCount < 2
    },
  })

  const isForbidden =
    detailQuery.error instanceof Error && detailQuery.error.message.includes('403')

  if (!job || !Number.isFinite(parsedAttemptId) || parsedAttemptId <= 0) {
    return (
      <div className="taste-panel p-8 text-center">
        <p className="text-sm text-ink-soft">Invalid run route — job and attempt id are required.</p>
        <Link to="/ops/runs" className="taste-link mt-4 inline-block text-sm">
          Back to runs
        </Link>
      </div>
    )
  }

  if (meLoading || detailQuery.isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonLines lines={2} />
        <div className="taste-panel p-6">
          <SkeletonLines lines={5} />
        </div>
      </div>
    )
  }

  if (isForbidden) {
    return <RunForbiddenState />
  }

  if (detailQuery.isError) {
    return (
      <div className="taste-panel p-8">
        <p className="text-sm text-red-700">Could not load run detail.</p>
        <p className="mt-2 font-mono text-xs text-ink-soft">
          {detailQuery.error instanceof Error ? detailQuery.error.message : 'Unknown error'}
        </p>
        <Link to="/ops/runs" className="taste-link mt-4 inline-block text-sm">
          Back to runs
        </Link>
      </div>
    )
  }

  const detail = detailQuery.data
  if (!detail) {
    return null
  }

  return (
    <section className="taste-ops-page space-y-5">
      <RunDetailHeader detail={detail} />
      <RunDetailTabs
        tab={tab}
        onTabChange={setTab}
        detail={detail}
        isSuperAdmin={isSuperAdmin}
      />
    </section>
  )
}
