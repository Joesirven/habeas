import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { RunTimeline } from '@/components/ops/RunTimeline'
import { getRunDetail, type RunDetail, type RunEvent } from '@/lib/api'
import { ForbiddenState, useMe } from '@/lib/auth'
import type { PipelineTab } from '@/router'

type DetailTab = 'timeline' | 'events'

const JOB_LABELS: Record<string, string> = {
  drop_connector: 'Download',
  drop_ingest: 'Ingest',
  matching: 'Matching',
  hash_index_refresh: 'Hash index refresh',
}

const CONSOLE_TAB_BY_JOB: Record<string, PipelineTab> = {
  drop_connector: 'download',
  drop_ingest: 'ingest',
  matching: 'matching',
  hash_index_refresh: 'configurations',
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
    normalized === 'failed_terminal'
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

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  if (minutes < 60) return remainder > 0 ? `${minutes}m ${remainder}s` : `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function RunDetailHeader({ detail }: { detail: RunDetail }) {
  const consoleTab = CONSOLE_TAB_BY_JOB[detail.job]

  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/ops/runs" className="taste-link text-xs">
          ← Runs
        </Link>
        <span className="taste-frost-chip">{jobLabel(detail.job)}</span>
        <span className={`taste-frost-chip ${runStatusClass(detail.status)}`}>{detail.status}</span>
      </div>
      <div>
        <Micro>Run detail</Micro>
        <h2 className="mt-2 font-display text-3xl font-medium tracking-tight text-ink">
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
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="taste-panel-soft px-4 py-3">
          <dt className="taste-micro">Started</dt>
          <dd className="mt-1 text-sm tabular-nums">{formatTimestamp(detail.started_at)}</dd>
        </div>
        <div className="taste-panel-soft px-4 py-3">
          <dt className="taste-micro">Completed</dt>
          <dd className="mt-1 text-sm tabular-nums">{formatTimestamp(detail.completed_at)}</dd>
        </div>
        <div className="taste-panel-soft px-4 py-3">
          <dt className="taste-micro">Duration</dt>
          <dd className="mt-1 text-sm tabular-nums">{formatDuration(detail.duration_seconds)}</dd>
        </div>
        <div className="taste-panel-soft px-4 py-3">
          <dt className="taste-micro">Attempt</dt>
          <dd className="mt-1 text-sm tabular-nums">
            {detail.attempt_number != null ? `#${detail.attempt_number}` : detail.attempt_id}
          </dd>
        </div>
      </dl>
      {consoleTab ? (
        <div>
          <Link
            to="/ops/drop-pipeline"
            search={{ tab: consoleTab }}
            className="taste-btn text-xs"
          >
            Open DROP console · {jobLabel(detail.job)}
          </Link>
        </div>
      ) : null}
    </header>
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

function PrivilegedErrorPanel({ detail, visible }: { detail: RunDetail; visible: boolean }) {
  if (!visible) return null

  const hasError = Boolean(detail.error_message || detail.error_code)

  return (
    <section className="taste-panel border-red-200/80 p-5 sm:p-6" aria-label="Privileged error details">
      <div>
        <Micro>Privileged · super admin</Micro>
        <h3 className="mt-1 font-display text-lg font-medium text-ink">Error panel</h3>
        <p className="mt-1 text-xs text-ink-soft">
          Redacted operator message only — stdout/stderr not persisted in v1.
        </p>
      </div>
      <dl className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <dt className="taste-micro">Error code</dt>
          <dd className="mt-1 font-mono text-sm">{detail.error_code ?? '—'}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="taste-micro">Error message (redacted)</dt>
          <dd className="mt-2 rounded-lg border border-line bg-paper/80 p-3 font-mono text-xs text-ink-soft">
            {hasError ? (
              <pre className="whitespace-pre-wrap break-words">{detail.error_message ?? '—'}</pre>
            ) : (
              <span>No error message on record.</span>
            )}
          </dd>
        </div>
      </dl>
    </section>
  )
}

function RunDetailTabs({
  tab,
  onTabChange,
  detail,
}: {
  tab: DetailTab
  onTabChange: (tab: DetailTab) => void
  detail: RunDetail
}) {
  return (
    <div className="taste-panel-soft flex flex-col gap-5 p-5 sm:p-6">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={tab === 'timeline' ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
          onClick={() => onTabChange('timeline')}
        >
          Timeline
        </button>
        <button
          type="button"
          className={tab === 'events' ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
          onClick={() => onTabChange('events')}
        >
          Events
          {detail.events.length > 0 ? (
            <span className="ml-1.5 tabular-nums text-[0.65rem] opacity-70">
              ({detail.events.length})
            </span>
          ) : null}
        </button>
      </div>
      {tab === 'timeline' ? (
        <RunTimeline steps={detail.timeline} />
      ) : (
        <RunEventsTable events={detail.events} />
      )}
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
  const [tab, setTab] = useState<DetailTab>('timeline')
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
    <div className="space-y-8">
      <RunDetailHeader detail={detail} />
      <RunDetailTabs tab={tab} onTabChange={setTab} detail={detail} />
      <PrivilegedErrorPanel detail={detail} visible={isSuperAdmin} />
    </div>
  )
}
