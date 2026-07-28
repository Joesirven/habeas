import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { RunTimeline } from '@/components/ops/RunTimeline'
import { Button } from '@/components/ui/button'
import {
  ConfirmActionDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { isLegalAdminPersona, useMe } from '@/lib/auth'
import {
  COARSE_STAGE_ORDER,
  stageLabel,
  type CoarseStageKey,
} from '@/lib/legalJourneyLabels'
import {
  getFulfillmentArtifact,
  getLatestIdentityVerification,
  getRequest,
  getRequestJourney,
  getRequestTimeline,
  getNeedsAttention,
  patchAccessDeliveryStatus,
  postIdentityVerification,
  postNoticeApprove,
  postRequestComment,
  postTriageBulkReject,
  postTriageSendToMatching,
  type JourneyStage,
  type MatchingResultDetail,
  type NeedsAttentionItem,
  type RequestRecord,
  type RunTimelineStep,
  type TimelineEntry,
} from '@/lib/api'
import { cn } from '@/lib/utils'

import {
  AccessHandoffPanel,
  MatchingReviewPanel,
  fetchMatchingDetailOptional,
  journeyStageToTimelineStep,
} from '@/components/requests/RequestTriageDialog'

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

export type RequestDetailTab = 'fulfillment' | 'matching' | 'activity'

export type RequestDetailOverlayProps = {
  requestId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Element to restore focus on close (KD36). */
  returnFocusRef?: RefObject<HTMLElement | null>
  /** Optional list-row context — avoids refetch for display label. */
  seedRequest?: RequestRecord | null
}

export function useRequestDetailOverlay() {
  const [open, setOpen] = useState(false)
  const [requestId, setRequestId] = useState<string | null>(null)
  const [seedRequest, setSeedRequest] = useState<RequestRecord | null>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)

  const openOverlay = useCallback(
    (id: string, trigger?: HTMLElement | null, seed?: RequestRecord | null) => {
      returnFocusRef.current =
        trigger ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null)
      setRequestId(id)
      setSeedRequest(seed ?? null)
      setOpen(true)
    },
    [],
  )

  const onOpenChange = useCallback((next: boolean) => {
    setOpen(next)
    if (!next) {
      setRequestId(null)
      setSeedRequest(null)
    }
  }, [])

  return {
    open,
    requestId,
    seedRequest,
    openOverlay,
    onOpenChange,
    returnFocusRef,
  }
}

export function requestDetailHeaderLabel(
  requestId: string,
  intakeSource: string,
  displayLabel?: string | null,
): string {
  const channel = SOURCE_LABELS[intakeSource] ?? intakeSource
  if (intakeSource === 'drop') {
    return `${requestId} · ${channel}`
  }
  return displayLabel?.trim() || requestId
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function mapTechnicalStageToCoarse(stage: string): CoarseStageKey {
  const normalized = stage.trim().toLowerCase()
  if (normalized === 'received' || normalized === 'triage') return 'receive'
  if (normalized === 'match' || ['download', 'land', 'promote'].includes(normalized)) {
    return 'matching'
  }
  if (normalized === 'review') return 'data_owner_review'
  if (normalized === 'fulfill' || normalized === 'fulfillment') return 'fulfillment'
  if (normalized === 'notice' || normalized === 'delivery') return 'delivery_notice'
  return 'legal_review'
}

function coarseStageRailSteps(
  journeyStages: JourneyStage[],
  currentStage: string,
): RunTimelineStep[] {
  const coarseStatuses = new Map<CoarseStageKey, RunTimelineStep['status']>()
  for (const key of COARSE_STAGE_ORDER) {
    coarseStatuses.set(key, 'pending')
  }

  for (const stage of journeyStages) {
    const coarse = mapTechnicalStageToCoarse(stage.stage)
    const status = journeyStageToTimelineStep(stage).status
    const existing = coarseStatuses.get(coarse)
    if (existing === 'completed' || existing === 'failed') continue
    if (status === 'completed') coarseStatuses.set(coarse, 'completed')
    else if (status === 'failed') coarseStatuses.set(coarse, 'failed')
    else if (status === 'running' || status === 'waiting') coarseStatuses.set(coarse, 'running')
  }

  const currentCoarse = mapTechnicalStageToCoarse(currentStage)
  const currentIdx = COARSE_STAGE_ORDER.indexOf(currentCoarse)
  for (let index = 0; index < currentIdx; index += 1) {
    const key = COARSE_STAGE_ORDER[index]!
    if (coarseStatuses.get(key) === 'pending') coarseStatuses.set(key, 'completed')
  }
  if (coarseStatuses.get(currentCoarse) === 'pending') {
    coarseStatuses.set(currentCoarse, 'running')
  }

  return COARSE_STAGE_ORDER.map((key) => ({
    key,
    label: stageLabel(key),
    status: coarseStatuses.get(key) ?? 'pending',
    timestamp: null,
  }))
}

function isTriageContext(item: NeedsAttentionItem | undefined, journeyStage: string): boolean {
  if (!item) return journeyStage === 'triage'
  return (
    item.kind === 'triage' ||
    item.assignment?.kind === 'triage' ||
    item.current_stage === 'triage'
  )
}

function isNoticeContext(item: NeedsAttentionItem | undefined, journeyStage: string): boolean {
  if (item?.kind === 'notice' || item?.reason === 'notice.review') return true
  return journeyStage === 'notice'
}

function isDeliveryContext(item: NeedsAttentionItem | undefined, journeyStage: string): boolean {
  if (
    item?.kind === 'delivery' ||
    item?.reason === 'access.delivery' ||
    item?.reason === 'delivery.confirm'
  ) {
    return true
  }
  return journeyStage === 'delivery' || journeyStage === 'fulfill'
}

function isAssignmentToLegalContext(item: NeedsAttentionItem | undefined): boolean {
  if (!item) return false
  return (
    item.kind === 'escalations' ||
    item.assignment?.kind === 'escalate' ||
    item.assignment?.target_role === 'legal'
  )
}

type StageAction = {
  id: string
  label: string
  hint?: string
  primary?: boolean
  destructive?: boolean
  softWarning?: string
  run: () => Promise<void>
}

function buildStageActions(opts: {
  requestId: string
  journeyStage: string
  attentionItem?: NeedsAttentionItem
  artifactPending?: boolean
  accessDelivered?: boolean
}): StageAction[] {
  const { requestId, journeyStage, attentionItem, artifactPending, accessDelivered } = opts
  const actions: StageAction[] = []

  if (isTriageContext(attentionItem, journeyStage)) {
    actions.push(
      {
        id: 'triage_reject',
        label: 'Reject as Exempted',
        hint: 'DROP response_status 2 — release pre-matching hold',
        run: async () => {
          await postTriageBulkReject({ request_ids: [requestId], response_status: 2 })
        },
      },
      {
        id: 'triage_match',
        label: 'Send to matching',
        primary: true,
        hint: 'Release hold and enqueue matching',
        run: async () => {
          await postTriageSendToMatching({ request_ids: [requestId] })
        },
      },
    )
  }

  if (isNoticeContext(attentionItem, journeyStage)) {
    actions.push({
      id: 'notice_approve',
      label: 'Approve notice review',
      primary: true,
      hint: 'Clear notice.review for weekly DROP upload',
      run: async () => {
        await postNoticeApprove({ request_ids: [requestId] })
      },
    })
  }

  if (isDeliveryContext(attentionItem, journeyStage)) {
    actions.push(
      {
        id: 'delivery_delivered',
        label: 'Confirm delivered',
        primary: true,
        run: async () => {
          await patchAccessDeliveryStatus(requestId, { status: 'delivered' })
        },
      },
      {
        id: 'delivery_failed',
        label: 'Mark delivery failed',
        destructive: true,
        run: async () => {
          await patchAccessDeliveryStatus(requestId, { status: 'failed' })
        },
      },
    )
  }

  actions.push({
    id: 'idv_verified',
    label: 'Identity verified',
    primary: actions.length === 0,
    hint: 'Record identity verification on Fulfillment tab',
    run: async () => {
      await postIdentityVerification(requestId, { status: 'verified', method: 'manual' })
    },
  })

  const incompleteWarning =
    artifactPending && !accessDelivered
      ? 'Access delivery may still be in progress.'
      : undefined

  actions.push({
    id: 'close',
    label: 'Close request',
    softWarning: incompleteWarning,
    hint: 'Unrestricted close (KD40) — records operator note',
    run: async () => {
      await postRequestComment(requestId, 'Operator closed request from detail overlay.')
    },
  })

  return actions
}

function RequestStageActionBar({
  actions,
  onInvalidate,
}: {
  actions: StageAction[]
  onInvalidate: () => Promise<void>
}) {
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmAction, setConfirmAction] = useState<StageAction | null>(null)

  const runAction = useMutation({
    mutationFn: async (action: StageAction) => {
      setPendingId(action.id)
      await action.run()
    },
    onSuccess: async () => {
      setError(null)
      setConfirmAction(null)
      setPendingId(null)
      await onInvalidate()
    },
    onError: (mutationError) => {
      setPendingId(null)
      setError(
        mutationError instanceof Error ? mutationError.message : 'Action failed — retry needed',
      )
    },
  })

  if (actions.length === 0) return null

  return (
    <div className="border-b border-line bg-panel/30 px-4 py-3">
      <p className="taste-micro mb-2">Stage actions</p>
      <div className="flex flex-wrap gap-2">
        {actions.map((action) => (
          <Button
            key={action.id}
            size="sm"
            variant={action.destructive ? 'outline' : action.primary ? 'default' : 'outline'}
            disabled={pendingId != null}
            className={cn(action.destructive && 'border-red-300 text-red-800 hover:bg-red-50')}
            onClick={() => {
              if (action.softWarning || action.id === 'close') {
                setConfirmAction(action)
                return
              }
              runAction.mutate(action)
            }}
          >
            {pendingId === action.id ? 'Working…' : action.label}
          </Button>
        ))}
      </div>
      {error ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <p className="text-[0.65rem] text-red-700">{error}</p>
          <Button
            size="sm"
            variant="outline"
            disabled={runAction.isPending}
            onClick={() => {
              const last = actions.find((action) => action.id === pendingId)
              if (last) runAction.mutate(last)
            }}
          >
            Retry
          </Button>
        </div>
      ) : null}
      <ConfirmActionDialog
        open={confirmAction != null}
        onOpenChange={(next) => {
          if (!next && !runAction.isPending) setConfirmAction(null)
        }}
        title={confirmAction?.label ?? 'Confirm'}
        description={
          confirmAction?.softWarning
            ? `${confirmAction.softWarning} This does not block close.`
            : (confirmAction?.hint ?? 'Confirm this action.')
        }
        confirmLabel={confirmAction?.label ?? 'Confirm'}
        confirming={runAction.isPending}
        onConfirm={() => {
          if (confirmAction) runAction.mutate(confirmAction)
        }}
      />
    </div>
  )
}

function RequesterMetaRail({
  requestId,
  intakeSource,
  displayLabel,
  requestorState,
  identityStatus,
  matching,
}: {
  requestId: string
  intakeSource: string
  displayLabel?: string | null
  requestorState?: string | null
  identityStatus?: string | null
  matching?: MatchingResultDetail | null
}) {
  const channel = SOURCE_LABELS[intakeSource] ?? intakeSource
  const isDrop = intakeSource === 'drop'
  const contact = matching?.matched_contacts?.[0]

  return (
    <aside className="space-y-3 border-l border-line bg-paper/40 p-4 text-xs lg:w-56 shrink-0">
      <p className="taste-micro">Requester</p>
      <dl className="space-y-2">
        <div>
          <dt className="text-[0.65rem] text-mute">Display</dt>
          <dd className="font-mono text-[0.7rem]">
            {requestDetailHeaderLabel(requestId, intakeSource, displayLabel)}
          </dd>
        </div>
        <div>
          <dt className="text-[0.65rem] text-mute">Channel</dt>
          <dd>{channel}</dd>
        </div>
        <div>
          <dt className="text-[0.65rem] text-mute">State</dt>
          <dd className="font-mono">{requestorState ?? matching?.requestor_state ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-[0.65rem] text-mute">Identity verification</dt>
          <dd className="capitalize">{identityStatus ?? 'none recorded'}</dd>
        </div>
        {!isDrop && displayLabel ? (
          <div>
            <dt className="text-[0.65rem] text-mute">Name</dt>
            <dd>{displayLabel}</dd>
          </div>
        ) : null}
        {contact?.email ? (
          <div>
            <dt className="text-[0.65rem] text-mute">Email</dt>
            <dd>{contact.email}</dd>
          </div>
        ) : null}
        {contact?.phones?.length ? (
          <div>
            <dt className="text-[0.65rem] text-mute">Phone</dt>
            <dd>
              {contact.phones.map((phone) => `${phone.type}: ${phone.number}`).join(' · ')}
            </dd>
          </div>
        ) : null}
      </dl>
    </aside>
  )
}

function ActivityPanel({
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
    <div className="grid gap-4 p-4 lg:grid-cols-[1fr_16rem]">
      <div className="space-y-3">
        <p className="taste-micro">Activity timeline</p>
        {isPending ? <SkeletonLines lines={4} /> : null}
        {!isPending && entries.length === 0 ? (
          <p className="text-xs text-ink-soft">No activity yet.</p>
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
              {entry.actor ? <p className="mt-1 text-mute">{entry.actor}</p> : null}
            </li>
          ))}
        </ol>
      </div>
      <div className="space-y-2">
        <p className="taste-micro">Add comment</p>
        <textarea
          className="min-h-[5rem] w-full rounded-lg border border-line bg-paper-raised px-3 py-2 text-xs text-ink"
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

export function RequestDetailBody({
  requestId,
  variant = 'overlay',
  defaultTab = 'fulfillment',
  seedRequest,
}: {
  requestId: string
  variant?: 'overlay' | 'page'
  defaultTab?: RequestDetailTab
  seedRequest?: RequestRecord | null
}) {
  const queryClient = useQueryClient()
  const { isAdmin, isSuperAdmin, role } = useMe()
  const legalAdmin = isLegalAdminPersona(role)
  const [tab, setTab] = useState<RequestDetailTab>(defaultTab)
  const [copyNote, setCopyNote] = useState<string | null>(null)

  const requestQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestId],
    queryFn: () => getRequest(requestId),
    enabled: Boolean(requestId),
    initialData: seedRequest ?? undefined,
    placeholderData: (previous) => previous,
  })

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey'],
    queryFn: () => getRequestJourney(requestId),
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const matchingQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop', 'matching-results', requestId],
    queryFn: () => fetchMatchingDetailOptional(requestId),
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const artifactQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', requestId],
    queryFn: () => getFulfillmentArtifact(requestId),
    refetchInterval: 15_000,
    retry: false,
  })

  const identityQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestId, 'identity-verification'],
    queryFn: () => getLatestIdentityVerification(requestId),
    refetchInterval: 15_000,
  })

  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention', 'overlay', requestId],
    queryFn: async () => {
      const response = await getNeedsAttention(200)
      return response.items.find((item) => item.request_id === requestId)
    },
    staleTime: 10_000,
  })

  const timelineQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'timeline'],
    queryFn: () => getRequestTimeline(requestId),
    enabled: tab === 'activity',
    refetchInterval: tab === 'activity' ? 15_000 : false,
    placeholderData: (previous) => previous,
  })

  const deliveryMutation = useMutation({
    mutationFn: (status: 'delivered' | 'failed' | 'recalled') =>
      patchAccessDeliveryStatus(requestId, { status }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
  })

  const invalidateAll = async () => {
    await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
  }

  const journey = journeyQuery.data
  const matching = matchingQuery.data
  const attentionItem = attentionQuery.data
  const intakeSource = journey?.intake_source ?? requestQuery.data?.intake_source ?? 'manual'
  const displayLabel = requestQuery.data?.display_label
  const coarseSteps = journey
    ? coarseStageRailSteps(journey.stages, journey.current_stage)
    : []

  const assignmentToLegal = isAssignmentToLegalContext(attentionItem)
  const canMatchingDisposition =
    !legalAdmin &&
    isAdmin &&
    matching != null &&
    matching.review_status === 'pending' &&
    Boolean(matching.approval_id)

  const stageActions = journey
    ? buildStageActions({
        requestId,
        journeyStage: journey.current_stage,
        attentionItem,
        artifactPending: Boolean(
          artifactQuery.data?.shareable_url || artifactQuery.data?.fulfillment_artifact_uri,
        ),
        accessDelivered: artifactQuery.data?.access_delivery_status === 'delivered',
      })
    : []

  const loading = journeyQuery.isPending && !journey

  if (loading) {
    return (
      <div className="px-4 py-8">
        <SkeletonLines lines={6} />
      </div>
    )
  }

  if (journeyQuery.isError || !journey) {
    return (
      <div className="px-4 py-6 text-xs text-red-700">
        Could not load request journey.
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <RequestStageActionBar actions={stageActions} onInvalidate={invalidateAll} />
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="overflow-x-auto border-b border-line px-4 py-3">
            <RunTimeline
              steps={coarseSteps}
              orientation="horizontal"
              emptyMessage="No stage rail."
            />
          </div>
          <Tabs value={tab} onValueChange={(value) => setTab(value as RequestDetailTab)}>
            <TabsList className="mx-4 mt-3">
              <TabsTrigger value="fulfillment">Fulfillment</TabsTrigger>
              <TabsTrigger value="matching">Matching</TabsTrigger>
              <TabsTrigger value="activity">Activity</TabsTrigger>
            </TabsList>
            <TabsContent value="fulfillment" className="px-4 pb-6">
              <div className="space-y-4">
                <AccessHandoffPanel
                  requestId={requestId}
                  artifact={artifactQuery.data}
                  isPending={artifactQuery.isPending}
                  isError={artifactQuery.isError}
                  canMutate={Boolean(isSuperAdmin || isAdmin)}
                  busy={deliveryMutation.isPending}
                  onCopyUrl={() => {
                    const url =
                      artifactQuery.data?.shareable_url ??
                      artifactQuery.data?.fulfillment_artifact_uri
                    if (!url) return
                    void navigator.clipboard.writeText(url).then(() => {
                      setCopyNote('Copied URL')
                      window.setTimeout(() => setCopyNote(null), 2000)
                    })
                  }}
                  onSetStatus={(status) => deliveryMutation.mutate(status)}
                />
                {copyNote ? <p className="taste-micro text-mute">{copyNote}</p> : null}
                {identityQuery.data ? (
                  <p className="text-xs text-ink-soft">
                    Latest identity verification:{' '}
                    <span className="capitalize text-ink">{identityQuery.data.status}</span>
                    <span className="text-mute">
                      {' '}
                      · {formatTimestamp(identityQuery.data.verified_at)}
                    </span>
                  </p>
                ) : (
                  <p className="text-xs text-mute">
                    No identity verification recorded — use stage actions or Fulfillment workflow.
                  </p>
                )}
              </div>
            </TabsContent>
            <TabsContent value="matching" className="px-4 pb-6">
              {assignmentToLegal ? (
                <p className="mb-2 text-[0.65rem] text-habeas-navy">
                  Assignment to legal — review matching context (disposition remains data-owner
                  canonical unless escalated here).
                </p>
              ) : legalAdmin ? (
                <p className="mb-2 text-[0.65rem] text-mute">
                  Read-only for legal/admin — matching disposition is data-owner-owned (KTD11).
                </p>
              ) : null}
              <MatchingReviewPanel
                requestId={requestId}
                matching={matching}
                isPending={matchingQuery.isPending}
                isError={matchingQuery.isError}
                canReviewActions={canMatchingDisposition}
                actionPending={false}
                actionError={null}
                hideActions={legalAdmin || !canMatchingDisposition}
                layout="tabs"
                compact
                onPromote={() => undefined}
                onDecline={() => undefined}
              />
            </TabsContent>
            <TabsContent value="activity">
              <ActivityPanel
                requestId={requestId}
                entries={timelineQuery.data?.entries ?? []}
                isPending={timelineQuery.isPending && !timelineQuery.data}
              />
            </TabsContent>
          </Tabs>
          {variant === 'overlay' ? (
            <div className="flex flex-wrap gap-2 border-t border-line px-4 py-3">
              <Link
                to="/requests/$requestId"
                params={{ requestId }}
                className="taste-btn text-xs"
              >
                Open full page →
              </Link>
              {isSuperAdmin ? (
                <Link
                  to="/ops/runs"
                  search={{ request_id: requestId }}
                  className="taste-btn text-xs"
                >
                  Runs for request →
                </Link>
              ) : null}
            </div>
          ) : null}
        </div>
        <RequesterMetaRail
          requestId={requestId}
          intakeSource={intakeSource}
          displayLabel={displayLabel}
          requestorState={requestQuery.data?.requestor_state}
          identityStatus={identityQuery.data?.status}
          matching={matching}
        />
      </div>
    </div>
  )
}

export function RequestDetailOverlay({
  requestId,
  open,
  onOpenChange,
  returnFocusRef,
  seedRequest,
}: RequestDetailOverlayProps) {
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const timer = window.setTimeout(() => {
      const focusable = contentRef.current?.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      focusable?.focus()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [open, requestId])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={contentRef}
        className={cn(
          'flex h-[90vh] max-h-[90vh] w-[95vw] max-w-[95vw] flex-col gap-0 overflow-hidden p-0',
          'translate-x-[-50%] translate-y-[-50%]',
        )}
        onCloseAutoFocus={(event) => {
          const target = returnFocusRef?.current
          if (target) {
            event.preventDefault()
            target.focus()
          }
        }}
        onEscapeKeyDown={() => onOpenChange(false)}
      >
        <DialogHeader className="shrink-0 border-b border-line px-5 py-4 pr-12">
          <p className="taste-micro">Request detail</p>
          <DialogTitle className="font-mono text-base">
            {requestId
              ? requestDetailHeaderLabel(
                  requestId,
                  seedRequest?.intake_source ?? 'manual',
                  seedRequest?.display_label,
                )
              : '—'}
          </DialogTitle>
          <DialogDescription>
            Fulfillment-default review — matching read-only for legal/admin unless assignment to
            legal.
          </DialogDescription>
        </DialogHeader>
        {requestId && open ? (
          <RequestDetailBody
            requestId={requestId}
            variant="overlay"
            defaultTab="fulfillment"
            seedRequest={seedRequest}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
