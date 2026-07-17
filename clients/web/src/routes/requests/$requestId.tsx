import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { RunTimeline } from '@/components/ops/RunTimeline'
import {
  getRequestJourney,
  type JourneyStage,
  type RunTimelineStep,
} from '@/lib/api'

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function journeyStageToTimelineStep(stage: JourneyStage): RunTimelineStep {
  const statusMap: Record<JourneyStage['status'], RunTimelineStep['status']> = {
    not_started: 'pending',
    skipped: 'skipped',
    in_progress: 'running',
    waiting: 'running',
    complete: 'completed',
    failed: 'failed',
  }
  return {
    key: stage.stage,
    label: stage.label,
    status: statusMap[stage.status],
    timestamp: stage.completed_at ?? stage.attempted_at,
    detail: stage.blocker ?? undefined,
  }
}

function JourneyMeta({
  intakeSource,
  receivedAt,
  currentStage,
  blocker,
}: {
  intakeSource: string
  receivedAt: string | null
  currentStage: string
  blocker: string | null
}) {
  return (
    <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <div className="taste-panel-soft px-4 py-3">
        <dt className="taste-micro">Source</dt>
        <dd className="mt-1 text-sm">{SOURCE_LABELS[intakeSource] ?? intakeSource}</dd>
      </div>
      <div className="taste-panel-soft px-4 py-3">
        <dt className="taste-micro">Received</dt>
        <dd className="mt-1 text-sm tabular-nums">{formatTimestamp(receivedAt)}</dd>
      </div>
      <div className="taste-panel-soft px-4 py-3">
        <dt className="taste-micro">Current stage</dt>
        <dd className="mt-1 text-sm capitalize">{currentStage.replaceAll('_', ' ')}</dd>
      </div>
      <div className="taste-panel-soft px-4 py-3">
        <dt className="taste-micro">Blocker</dt>
        <dd className="mt-1 text-sm text-ink-soft">{blocker ?? '—'}</dd>
      </div>
    </dl>
  )
}

export function RequestDetailPage() {
  const { requestId } = useParams({ from: '/requests/$requestId' })

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey'],
    queryFn: () => getRequestJourney(requestId),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const loading = journeyQuery.isPending && !journeyQuery.data

  return (
    <section className="space-y-10">
      <header className="space-y-4">
        <Link to="/requests" className="taste-link text-xs">
          ← Requests
        </Link>
        <div>
          <Micro>Request</Micro>
          <div className="mt-3 flex flex-wrap items-baseline gap-3">
            <h2 className="font-display text-[2.25rem] font-medium tracking-tight text-ink">
              <span className="font-mono text-2xl">{requestId}</span>
            </h2>
            {journeyQuery.isFetching && !journeyQuery.isPending ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
          </div>
          <p className="mt-3 max-w-xl text-sm text-ink-soft">
            Stage rail across intake, DROP pipeline, matching, review, and fulfillment — no PII.
          </p>
        </div>
      </header>

      {loading ? (
        <div className="taste-panel-soft p-6">
          <SkeletonLines lines={6} />
        </div>
      ) : null}

      {journeyQuery.isError ? (
        <div className="taste-panel p-6">
          <p className="text-sm text-red-700">Could not load request journey.</p>
          <p className="mt-2 font-mono text-xs text-ink-soft">
            {journeyQuery.error instanceof Error ? journeyQuery.error.message : 'Unknown error'}
          </p>
        </div>
      ) : null}

      {journeyQuery.data ? (
        <>
          <JourneyMeta
            intakeSource={journeyQuery.data.intake_source}
            receivedAt={journeyQuery.data.received_at}
            currentStage={journeyQuery.data.current_stage}
            blocker={journeyQuery.data.blocker}
          />
          <div className="taste-panel-soft p-6 sm:p-7">
            <Micro>Journey</Micro>
            <div className="mt-4">
              <RunTimeline
                steps={journeyQuery.data.stages.map(journeyStageToTimelineStep)}
                emptyMessage="No journey stages recorded."
              />
            </div>
          </div>
        </>
      ) : null}
    </section>
  )
}
