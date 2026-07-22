import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { MatchingReviewPanel } from '@/components/requests/RequestTriageDialog'
import { RunTimeline } from '@/components/ops/RunTimeline'
import { useMe } from '@/lib/auth'
import {
  getDropMatchingResultDetail,
  getRequestJourney,
  postDropMatchingResultDecline,
  postDropMatchingResultPromote,
  type JourneyStage,
  type MatchingResultDetail,
  type RunTimelineStep,
} from '@/lib/api'

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

type RequestTab = 'overview' | 'journey' | 'matching'

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
    waiting: 'waiting',
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

function MetaStrip({
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
    <dl className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line px-4 py-3 text-xs">
      <div className="flex items-baseline gap-2">
        <dt className="taste-micro">Source</dt>
        <dd>{SOURCE_LABELS[intakeSource] ?? intakeSource}</dd>
      </div>
      <div className="flex items-baseline gap-2">
        <dt className="taste-micro">Received</dt>
        <dd className="tabular-nums">{formatTimestamp(receivedAt)}</dd>
      </div>
      <div className="flex items-baseline gap-2">
        <dt className="taste-micro">Stage</dt>
        <dd className="capitalize">
          <span className="taste-frost-chip text-[0.65rem]">
            {(currentStage ?? 'unknown').replaceAll('_', ' ')}
          </span>
        </dd>
      </div>
      <div className="flex min-w-0 items-baseline gap-2">
        <dt className="taste-micro shrink-0">Blocker</dt>
        <dd className="truncate text-ink-soft">{blocker ?? '—'}</dd>
      </div>
    </dl>
  )
}

function RequestTabs({
  tab,
  onTabChange,
}: {
  tab: RequestTab
  onTabChange: (tab: RequestTab) => void
}) {
  const tabs: { id: RequestTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'journey', label: 'Journey' },
    { id: 'matching', label: 'Matching' },
  ]

  return (
    <div className="flex flex-wrap gap-2 border-b border-line px-4 py-3">
      {tabs.map((item) => (
        <button
          key={item.id}
          type="button"
          className={tab === item.id ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
          onClick={() => onTabChange(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}

function OverviewPanel({
  intakeSource,
  receivedAt,
  currentStage,
  blocker,
  timelineSteps,
}: {
  intakeSource: string
  receivedAt: string | null
  currentStage: string
  blocker: string | null
  timelineSteps: RunTimelineStep[]
}) {
  const runningStage = timelineSteps.find((step) => step.status === 'running')
  const failedStage = timelineSteps.find((step) => step.status === 'failed')

  return (
    <div className="space-y-4 p-4">
      <div className="overflow-x-auto">
        <RunTimeline
          steps={timelineSteps}
          orientation="horizontal"
          emptyMessage="No journey stages recorded."
        />
      </div>
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2">
          <dt className="taste-micro">Intake channel</dt>
          <dd className="mt-1 text-xs">{SOURCE_LABELS[intakeSource] ?? intakeSource}</dd>
        </div>
        <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2">
          <dt className="taste-micro">Received</dt>
          <dd className="mt-1 text-xs tabular-nums">{formatTimestamp(receivedAt)}</dd>
        </div>
        <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2">
          <dt className="taste-micro">Current stage</dt>
          <dd className="mt-1 text-xs capitalize">
            {(currentStage ?? 'unknown').replaceAll('_', ' ')}
          </dd>
        </div>
        {runningStage ? (
          <div className="rounded-lg border border-habeas-mid/30 bg-panel/60 px-3 py-2 sm:col-span-2">
            <dt className="taste-micro">In progress</dt>
            <dd className="mt-1 text-xs text-habeas-navy">{runningStage.label}</dd>
          </div>
        ) : null}
        {failedStage ? (
          <div className="rounded-lg border border-red-200/80 bg-red-50/50 px-3 py-2 sm:col-span-2">
            <dt className="taste-micro">Failed stage</dt>
            <dd className="mt-1 text-xs text-red-800">
              {failedStage.label}
              {failedStage.detail ? ` — ${failedStage.detail}` : ''}
            </dd>
          </div>
        ) : null}
        {blocker ? (
          <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2 sm:col-span-2 lg:col-span-3">
            <dt className="taste-micro">Blocker</dt>
            <dd className="mt-1 text-xs text-ink-soft">{blocker}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  )
}

function JourneyPanel({ timelineSteps }: { timelineSteps: RunTimelineStep[] }) {
  return (
    <div className="space-y-5 p-4">
      <div>
        <Micro>Stage rail</Micro>
        <div className="mt-3 overflow-x-auto">
          <RunTimeline
            steps={timelineSteps}
            orientation="horizontal"
            emptyMessage="No journey stages recorded."
          />
        </div>
      </div>
      <div className="border-t border-line pt-4">
        <Micro>Stage detail</Micro>
        <div className="mt-3">
          <RunTimeline steps={timelineSteps} emptyMessage="No journey stages recorded." />
        </div>
      </div>
    </div>
  )
}

async function fetchMatchingDetailOptional(
  requestId: string,
): Promise<MatchingResultDetail | null> {
  try {
    return await getDropMatchingResultDetail(requestId)
  } catch (error) {
    if (
      error instanceof Error &&
      (error.message.includes('404') ||
        error.message.includes('500') ||
        error.message.includes('502') ||
        error.message.includes('503'))
    ) {
      return null
    }
    throw error
  }
}

function MatchingPanel({ requestId }: { requestId: string }) {
  const queryClient = useQueryClient()
  const { isAdmin } = useMe()
  const [actionError, setActionError] = useState<string | null>(null)

  const matchingQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop', 'matching-results', requestId],
    queryFn: () => fetchMatchingDetailOptional(requestId),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const promoteMutation = useMutation({
    mutationFn: () => postDropMatchingResultPromote(requestId),
    onSuccess: async () => {
      setActionError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Promote failed')
    },
  })

  const declineMutation = useMutation({
    mutationFn: () => postDropMatchingResultDecline(requestId),
    onSuccess: async () => {
      setActionError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Decline failed')
    },
  })

  const matching = matchingQuery.data
  const actionPending = promoteMutation.isPending || declineMutation.isPending
  const canReviewActions =
    isAdmin &&
    matching != null &&
    matching.review_status === 'pending' &&
    Boolean(matching.approval_id)

  return (
    <div className="p-4">
      <MatchingReviewPanel
        requestId={requestId}
        matching={matching}
        isPending={matchingQuery.isPending}
        isError={matchingQuery.isError}
        canReviewActions={canReviewActions}
        actionPending={actionPending}
        actionError={actionError}
        onPromote={() => promoteMutation.mutate()}
        onDecline={() => declineMutation.mutate()}
      />
    </div>
  )
}

export function RequestDetailPage() {
  const { requestId } = useParams({ from: '/requests/$requestId' })
  const { isSuperAdmin } = useMe()
  const [tab, setTab] = useState<RequestTab>('overview')

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey'],
    queryFn: () => getRequestJourney(requestId),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const loading = journeyQuery.isPending && !journeyQuery.data
  const timelineSteps =
    journeyQuery.data?.stages.map(journeyStageToTimelineStep) ?? []

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <Link to="/requests" className="taste-link text-xs">
            ← Requests
          </Link>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-2">
            <h2 className="truncate font-mono text-lg font-medium tracking-tight text-ink">
              {requestId}
            </h2>
            {journeyQuery.isFetching && !journeyQuery.isPending ? (
              <span className="taste-frost-chip text-[0.65rem]">Refreshing</span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isSuperAdmin ? (
            <Link
              to="/ops/runs"
              search={{ request_id: requestId, window: '1w' }}
              className="taste-btn text-xs"
            >
              Runs for request
            </Link>
          ) : null}
          <Link to="/requests/needs-attention" className="taste-btn text-xs">
            Needs attention
          </Link>
        </div>
      </header>

      {loading ? (
        <div className="taste-panel p-4">
          <SkeletonLines lines={5} />
        </div>
      ) : null}

      {journeyQuery.isError ? (
        <div className="taste-panel p-4">
          <p className="text-xs text-red-700">Could not load request journey.</p>
          <p className="mt-2 font-mono text-[0.65rem] text-ink-soft">
            {journeyQuery.error instanceof Error ? journeyQuery.error.message : 'Unknown error'}
          </p>
        </div>
      ) : null}

      {journeyQuery.data ? (
        <div className="taste-panel overflow-hidden">
          <MetaStrip
            intakeSource={journeyQuery.data.intake_source}
            receivedAt={journeyQuery.data.received_at}
            currentStage={journeyQuery.data.current_stage}
            blocker={journeyQuery.data.blocker}
          />
          <RequestTabs tab={tab} onTabChange={setTab} />
          {tab === 'overview' ? (
            <OverviewPanel
              intakeSource={journeyQuery.data.intake_source}
              receivedAt={journeyQuery.data.received_at}
              currentStage={journeyQuery.data.current_stage}
              blocker={journeyQuery.data.blocker}
              timelineSteps={timelineSteps}
            />
          ) : null}
          {tab === 'journey' ? <JourneyPanel timelineSteps={timelineSteps} /> : null}
          {tab === 'matching' ? <MatchingPanel requestId={requestId} /> : null}
        </div>
      ) : null}
    </section>
  )
}
