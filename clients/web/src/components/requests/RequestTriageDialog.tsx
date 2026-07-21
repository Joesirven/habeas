import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { RunTimeline } from '@/components/ops/RunTimeline'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
import { cn } from '@/lib/utils'

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

export type RequestDetailDrawerProps = {
  requestId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** @deprecated Prefer RequestDetailDrawer — same component. */
export type RequestTriageDialogProps = RequestDetailDrawerProps

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

async function fetchMatchingDetailOptional(
  requestId: string,
): Promise<MatchingResultDetail | null> {
  try {
    return await getDropMatchingResultDetail(requestId)
  } catch (error) {
    if (error instanceof Error && error.message.includes('404')) {
      return null
    }
    throw error
  }
}

function reviewStatusVariant(status: string): 'default' | 'ok' | 'fail' | 'wait' | 'run' {
  if (status === 'approved') return 'ok'
  if (status === 'declined') return 'fail'
  if (status === 'pending') return 'wait'
  return 'default'
}

export function MatchingReviewPanel({
  requestId,
  matching,
  isPending,
  isError,
  canReviewActions,
  actionPending,
  actionError,
  onPromote,
  onDecline,
}: {
  requestId: string
  matching: MatchingResultDetail | null | undefined
  isPending: boolean
  isError: boolean
  canReviewActions: boolean
  actionPending: boolean
  actionError: string | null
  onPromote: () => void
  onDecline: () => void
}) {
  return (
    <div className="space-y-4 text-xs">
      {isPending && matching == null ? (
        <p className="text-ink-soft">Loading matching result…</p>
      ) : null}
      {isError ? <p className="text-red-700">Could not load matching result.</p> : null}
      {matching == null && !isPending && !isError ? (
        <p className="text-ink-soft">No matching result recorded for this request yet.</p>
      ) : null}
      {matching ? (
        <>
          <dl className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2">
              <dt className="taste-micro">Matched</dt>
              <dd className="mt-1">{matching.matched ? 'Yes' : 'No'}</dd>
            </div>
            <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2">
              <dt className="taste-micro">Match count</dt>
              <dd className="mt-1 tabular-nums">{matching.match_count}</dd>
            </div>
            <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2">
              <dt className="taste-micro">Match type</dt>
              <dd className="mt-1">{matching.match_type.replaceAll('_', ' ')}</dd>
            </div>
            <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2">
              <dt className="taste-micro">Review status</dt>
              <dd className="mt-1">
                <Badge variant={reviewStatusVariant(matching.review_status)}>
                  {matching.review_status}
                </Badge>
              </dd>
            </div>
            <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2">
              <dt className="taste-micro">Matched via</dt>
              <dd className="mt-1">{matching.matched_via}</dd>
            </div>
            {matching.requestor_state ? (
              <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2">
                <dt className="taste-micro">Requestor state</dt>
                <dd className="mt-1 font-mono">{matching.requestor_state}</dd>
              </div>
            ) : null}
            {matching.recorded_at ? (
              <div className="rounded-lg border border-line/80 bg-paper/60 px-3 py-2">
                <dt className="taste-micro">Recorded</dt>
                <dd className="mt-1 tabular-nums">{formatTimestamp(matching.recorded_at)}</dd>
              </div>
            ) : null}
          </dl>

          {canReviewActions ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
              <Button size="sm" disabled={actionPending} onClick={onPromote}>
                Promote to fulfillment
              </Button>
              <Button size="sm" variant="outline" disabled={actionPending} onClick={onDecline}>
                Decline
              </Button>
            </div>
          ) : null}

          {actionError ? <p className="text-[0.65rem] text-red-700">{actionError}</p> : null}

          <p className="text-[0.65rem] text-mute">
            Review is scoped to{' '}
            <span className="font-mono text-ink-soft">{requestId}</span> — counts and ids only.
          </p>
        </>
      ) : null}
    </div>
  )
}

export function RequestDetailDrawer({ requestId, open, onOpenChange }: RequestDetailDrawerProps) {
  const queryClient = useQueryClient()
  const { isAdmin, isSuperAdmin } = useMe()
  const [actionError, setActionError] = useState<string | null>(null)

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey'],
    queryFn: () => getRequestJourney(requestId!),
    enabled: open && Boolean(requestId),
    refetchInterval: open ? 10_000 : false,
    placeholderData: (previous) => previous,
  })

  const matchingQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop', 'matching-results', requestId],
    queryFn: () => fetchMatchingDetailOptional(requestId!),
    enabled: open && Boolean(requestId),
    refetchInterval: open ? 10_000 : false,
    placeholderData: (previous) => previous,
  })

  const promoteMutation = useMutation({
    mutationFn: () => postDropMatchingResultPromote(requestId!),
    onSuccess: async () => {
      setActionError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Promote failed')
    },
  })

  const declineMutation = useMutation({
    mutationFn: () => postDropMatchingResultDecline(requestId!),
    onSuccess: async () => {
      setActionError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Decline failed')
    },
  })

  const timelineSteps = journeyQuery.data?.stages.map(journeyStageToTimelineStep) ?? []
  const matching = matchingQuery.data
  const loading = journeyQuery.isPending && !journeyQuery.data
  const actionPending = promoteMutation.isPending || declineMutation.isPending
  const canReviewActions =
    isAdmin &&
    matching != null &&
    matching.review_status === 'pending' &&
    Boolean(matching.approval_id)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          'inset-y-0 right-0 left-auto top-0 h-full max-h-none w-full max-w-xl translate-x-0 translate-y-0 gap-0 overflow-hidden rounded-none border-y-0 border-l border-r-0 p-0 shadow-xl sm:max-w-xl',
        )}
      >
        <DialogHeader className="shrink-0 border-b border-line px-5 py-4 pr-12">
          <p className="taste-micro">Request detail</p>
          <DialogTitle className="font-mono text-base">{requestId ?? '—'}</DialogTitle>
          <DialogDescription>
            Full journey history and matching review — counts and ids only.
          </DialogDescription>
          {journeyQuery.isFetching && !journeyQuery.isPending ? (
            <span className="taste-frost-chip w-fit text-[0.65rem]">Refreshing</span>
          ) : null}
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {loading ? (
            <div className="px-5 py-8 text-xs text-ink-soft">Loading journey…</div>
          ) : null}

          {journeyQuery.isError ? (
            <div className="px-5 py-6">
              <p className="text-xs text-red-700">Could not load request journey.</p>
              <p className="mt-1 font-mono text-[0.65rem] text-ink-soft">
                {journeyQuery.error instanceof Error
                  ? journeyQuery.error.message
                  : 'Unknown error'}
              </p>
            </div>
          ) : null}

          {journeyQuery.data ? (
            <div className="px-5 pb-8">
              <dl className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line py-3 text-xs">
                <div className="flex items-baseline gap-2">
                  <dt className="taste-micro">Source</dt>
                  <dd>
                    {SOURCE_LABELS[journeyQuery.data.intake_source] ??
                      journeyQuery.data.intake_source}
                  </dd>
                </div>
                <div className="flex items-baseline gap-2">
                  <dt className="taste-micro">Received</dt>
                  <dd className="tabular-nums">
                    {formatTimestamp(journeyQuery.data.received_at)}
                  </dd>
                </div>
                <div className="flex items-baseline gap-2">
                  <dt className="taste-micro">Stage</dt>
                  <dd>
                    <span className="taste-frost-chip text-[0.65rem] capitalize">
                      {journeyQuery.data.current_stage.replaceAll('_', ' ')}
                    </span>
                  </dd>
                </div>
                {journeyQuery.data.blocker ? (
                  <div className="flex min-w-0 items-baseline gap-2 sm:max-w-md">
                    <dt className="taste-micro shrink-0">Blocker</dt>
                    <dd className="truncate text-ink-soft">{journeyQuery.data.blocker}</dd>
                  </div>
                ) : null}
              </dl>

              <Tabs defaultValue="history" className="mt-3">
                <TabsList>
                  <TabsTrigger value="history">History</TabsTrigger>
                  <TabsTrigger value="matching">Matching</TabsTrigger>
                </TabsList>

                <TabsContent value="history">
                  <div className="space-y-4">
                    <div className="overflow-x-auto rounded-lg border border-line/80 bg-paper/40 p-3">
                      <RunTimeline
                        steps={timelineSteps}
                        orientation="horizontal"
                        emptyMessage="No journey stages recorded."
                      />
                    </div>
                    <RunTimeline
                      steps={timelineSteps}
                      emptyMessage="No journey stages recorded."
                    />
                    <div className="flex flex-wrap gap-2 border-t border-line pt-4">
                      <Link
                        to="/requests/$requestId"
                        params={{ requestId: journeyQuery.data.request_id }}
                        className="taste-btn text-xs"
                        onClick={() => onOpenChange(false)}
                      >
                        Open full page →
                      </Link>
                      {isSuperAdmin ? (
                        <Link
                          to="/ops/runs"
                          search={{ request_id: journeyQuery.data.request_id }}
                          className="taste-btn text-xs"
                          onClick={() => onOpenChange(false)}
                        >
                          Runs for request →
                        </Link>
                      ) : null}
                    </div>
                  </div>
                </TabsContent>

                <TabsContent value="matching">
                  <MatchingReviewPanel
                    requestId={journeyQuery.data.request_id}
                    matching={matching}
                    isPending={matchingQuery.isPending}
                    isError={matchingQuery.isError}
                    canReviewActions={canReviewActions}
                    actionPending={actionPending}
                    actionError={actionError}
                    onPromote={() => promoteMutation.mutate()}
                    onDecline={() => declineMutation.mutate()}
                  />
                </TabsContent>
              </Tabs>
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** @deprecated Prefer RequestDetailDrawer. */
export const RequestTriageDialog = RequestDetailDrawer
