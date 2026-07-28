import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { MatchingReviewPanel } from '@/components/requests/RequestTriageDialog'
import { RunTimeline } from '@/components/ops/RunTimeline'
import { useMe, isLegalAdminPersona } from '@/lib/auth'
import { stageLabel } from '@/lib/legalJourneyLabels'
import {
  getDropMatchingResultDetail,
  getRequestJourney,
  getRequestTimeline,
  postDropMatchingResultDecline,
  postDropMatchingResultPromote,
  postRequestComment,
  type DropResponseStatusCode,
  type JourneyStage,
  type MatchingResultDetail,
  type RunTimelineStep,
  type TimelineEntry,
} from '@/lib/api'

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

type RequestTab = 'history' | 'overview' | 'journey' | 'matching'

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
    label: stageLabel(stage.stage),
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
        <dd>
          <span className="taste-frost-chip text-[0.65rem]">
            {stageLabel(currentStage ?? 'unknown')}
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
    { id: 'history', label: 'History' },
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
          <dd className="mt-1 text-xs">{stageLabel(currentStage ?? 'unknown')}</dd>
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
    mutationFn: (responseStatus: DropResponseStatusCode) =>
      postDropMatchingResultPromote(requestId, { response_status: responseStatus }),
    onSuccess: async () => {
      setActionError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Fulfill failed')
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
        onPromote={(responseStatus) => promoteMutation.mutate(responseStatus)}
        onDecline={() => declineMutation.mutate()}
      />
    </div>
  )
}

function HistoryPanel({
  requestId,
  entries,
  isPending,
}: {
  requestId: string
  entries: TimelineEntry[]
  isPending: boolean
}) {
  const queryClient = useQueryClient()
  const [comment, setComment] = useState('')
  const [error, setError] = useState<string | null>(null)

  const commentMutation = useMutation({
    mutationFn: () => postRequestComment(requestId, comment.trim()),
    onSuccess: async () => {
      setComment('')
      setError(null)
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'requests', requestId, 'timeline'],
      })
    },
    onError: (err) => {
      setError(err instanceof Error ? err.message : 'Comment failed')
    },
  })

  return (
    <div className="grid gap-4 p-4 lg:grid-cols-[1fr_18rem]">
      <div className="space-y-3">
        <p className="taste-micro">Timeline</p>
        {isPending ? <SkeletonLines lines={4} /> : null}
        {!isPending && entries.length === 0 ? (
          <p className="text-xs text-ink-soft">No history yet.</p>
        ) : null}
        <ol className="space-y-2">
          {entries.map((entry, index) => (
            <li
              key={`${entry.at}-${entry.kind}-${index}`}
              className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2 text-xs"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="taste-frost-chip text-[0.65rem] capitalize">{entry.kind}</span>
                <time className="tabular-nums text-mute">{formatTimestamp(entry.at)}</time>
              </div>
              <p className="mt-1 text-ink">{entry.summary}</p>
              {entry.actor ? (
                <p className="mt-1 text-mute">{entry.actor}</p>
              ) : null}
            </li>
          ))}
        </ol>
      </div>
      <div className="space-y-2">
        <p className="taste-micro">Add comment</p>
        <textarea
          className="min-h-[6rem] w-full rounded-lg border border-line bg-paper-raised px-3 py-2 text-xs text-ink"
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          maxLength={2000}
        />
        <button
          type="button"
          className="taste-btn-primary text-xs"
          disabled={comment.trim().length === 0 || commentMutation.isPending}
          onClick={() => commentMutation.mutate()}
        >
          {commentMutation.isPending ? 'Posting…' : 'Post comment'}
        </button>
        {error ? <p className="text-xs text-red-700">{error}</p> : null}
      </div>
    </div>
  )
}

export function RequestDetailPage() {
  const { requestId } = useParams({ from: '/requests/$requestId' })
  const { isSuperAdmin, role } = useMe()
  const legalAdmin = isLegalAdminPersona(role)
  const [tab, setTab] = useState<RequestTab>(legalAdmin ? 'history' : 'overview')

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey'],
    queryFn: () => getRequestJourney(requestId),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const timelineQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'timeline'],
    queryFn: () => getRequestTimeline(requestId),
    refetchInterval: 10_000,
    enabled: legalAdmin || tab === 'history',
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
            ← All requests
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
          {tab === 'history' ? (
            <HistoryPanel
              requestId={requestId}
              entries={timelineQuery.data?.entries ?? []}
              isPending={timelineQuery.isPending && !timelineQuery.data}
            />
          ) : null}
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
