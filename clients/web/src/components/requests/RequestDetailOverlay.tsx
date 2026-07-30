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
import { AccessDeliveryEmailCard } from '@/components/fulfillment/AccessDeliveryEmail'
import { RunTimeline } from '@/components/ops/RunTimeline'
import { Badge } from '@/components/ui/badge'
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
  NOTICE_APPROVAL,
  actionReasonLabel,
  stageLabel,
  workbenchStatusLabel,
  type CoarseStageKey,
} from '@/lib/legalJourneyLabels'
import {
  dropResponseStatusLabel,
  getFulfillmentArtifact,
  getLatestIdentityVerification,
  getRequest,
  getRequestJourney,
  getRequestJourneyWorkbench,
  getRequestTimeline,
  getNeedsAttention,
  patchAccessDeliveryStatus,
  postFulfillmentKickoff,
  postIdentityVerification,
  postNoticeApprove,
  postRequestClose,
  postRequestComment,
  postDropMatchingResultDecline,
  postDropMatchingResultPromote,
  postTriageBulkReject,
  postTriageSendToMatching,
  type DropResponseStatusCode,
  type JourneyStage,
  type JourneyStageStatus,
  type MatchedPersonContact,
  type MatchingResultDetail,
  type NeedsAttentionItem,
  type RequestJourneyResponse,
  type RequestRecord,
  type RequesterContact,
  type RunTimelineStep,
  type TimelineEntry,
  type WorkbenchStage,
  type WorkbenchVerticalRow,
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

export type RequestDetailTab = 'details' | 'fulfillment' | 'matching' | 'activity'

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

function journeyResponseStatus(
  journey: RequestJourneyResponse | null | undefined,
): number | null {
  const value = journey?.response_status
  return typeof value === 'number' ? value : null
}

function resolveDropStatusCode(opts: {
  journey?: RequestJourneyResponse | null
  matching?: MatchingResultDetail | null
  attentionItem?: NeedsAttentionItem | null
}): { code: number | null; isRecommended: boolean } {
  const fromJourney = journeyResponseStatus(opts.journey)
  if (fromJourney != null) return { code: fromJourney, isRecommended: false }
  // Fulfilled notice/delivery rows carry response_status on needs-attention.
  const fromAttention = opts.attentionItem?.response_status
  if (typeof fromAttention === 'number') {
    return { code: fromAttention, isRecommended: false }
  }
  const recommended =
    opts.matching?.recommended_response_status ??
    opts.attentionItem?.recommended_response_status
  if (typeof recommended === 'number') {
    return { code: recommended, isRecommended: true }
  }
  return { code: null, isRecommended: false }
}

function matchingResultsLabel(matching: MatchingResultDetail): string {
  const type = (matching.match_type ?? (matching.matched ? 'matched' : 'not matched')).replaceAll(
    '_',
    ' ',
  )
  return `${type} · ${matching.match_count}`
}

function matchingStatusLabel(reviewStatus: string): string {
  const normalized = reviewStatus.trim().toLowerCase()
  if (normalized === 'pending') return 'Pending review'
  if (normalized === 'approved') return 'Approved'
  if (normalized === 'declined' || normalized === 'rejected') return 'Declined'
  if (normalized === 'none' || normalized === '') return 'None'
  return reviewStatus.replaceAll('_', ' ')
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

const WORKBENCH_STATUS_TO_TIMELINE: Record<JourneyStageStatus, RunTimelineStep['status']> = {
  not_started: 'pending',
  skipped: 'skipped',
  in_progress: 'running',
  waiting: 'waiting',
  complete: 'completed',
  failed: 'failed',
}

/** KTD2 four-stage rail (Ingest → Matching → Fulfillment → Notice), U4 workbench DTO. */
function workbenchRailSteps(stages: WorkbenchStage[]): RunTimelineStep[] {
  return stages.map((stage) => ({
    key: stage.stage,
    label: stage.label,
    status: WORKBENCH_STATUS_TO_TIMELINE[stage.status],
    timestamp: null,
    detail: stage.blocker ?? undefined,
  }))
}

function verticalIndicatorClass(status: JourneyStageStatus): string {
  switch (status) {
    case 'complete':
      return 'bg-habeas-mid'
    case 'failed':
      return 'bg-red-700/70'
    case 'in_progress':
      return 'bg-habeas-light animate-pulse ring-2 ring-habeas-mid/40'
    case 'waiting':
      return 'border-2 border-habeas-mid bg-paper'
    case 'skipped':
      return 'bg-line-strong'
    default:
      return 'border border-line-strong bg-paper'
  }
}

/** Matching or Fulfillment cluster — per-vertical rows (R2). Click opens that cluster's tab. */
function VerticalClusterList({
  title,
  rows,
  statusOf,
  onSelect,
}: {
  title: string
  rows: WorkbenchVerticalRow[]
  statusOf: (row: WorkbenchVerticalRow) => JourneyStageStatus | null
  onSelect: () => void
}) {
  if (rows.length === 0) return null
  return (
    <div className="min-w-0 flex-1 space-y-1.5">
      <p className="taste-micro">{title}</p>
      <ul className="space-y-1">
        {rows.map((row) => {
          const status = statusOf(row) ?? 'not_started'
          return (
            <li key={row.vertical}>
              <button
                type="button"
                disabled={!row.live}
                onClick={onSelect}
                className={cn(
                  'flex w-full items-center gap-2 rounded-md border border-line/70 bg-paper px-2 py-1.5 text-left text-xs',
                  row.live ? 'hover:border-ink/30' : 'opacity-50',
                )}
                title={row.blocker ?? undefined}
              >
                <span
                  className={cn('h-2.5 w-2.5 shrink-0 rounded-full', verticalIndicatorClass(status))}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1 truncate text-ink">{row.label}</span>
                <span className="shrink-0 text-[0.65rem] text-mute">
                  {row.live ? workbenchStatusLabel(status) : 'Coming soon'}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
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
  /** When set, show confirm dialog before running (title/description override softWarning path). */
  confirm?: { title: string; description: string }
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
      label: NOTICE_APPROVAL.action,
      primary: true,
      hint: NOTICE_APPROVAL.hint,
      confirm: {
        title: NOTICE_APPROVAL.confirmTitle,
        description: NOTICE_APPROVAL.hint,
      },
      run: async () => {
        await postNoticeApprove({ request_ids: [requestId] })
      },
    })
  }

  const noticeContext = isNoticeContext(attentionItem, journeyStage)
  // Fulfill stage historically matched delivery context — skip when the work is fulfillment notice.
  if (!noticeContext && isDeliveryContext(attentionItem, journeyStage)) {
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
      await postRequestClose(requestId, {
        note: 'Operator closed request from detail overlay.',
      })
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
  const [failedActionId, setFailedActionId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmAction, setConfirmAction] = useState<StageAction | null>(null)

  const runAction = useMutation({
    mutationFn: async (action: StageAction) => {
      setPendingId(action.id)
      setFailedActionId(null)
      await action.run()
    },
    onSuccess: async () => {
      setError(null)
      setConfirmAction(null)
      setPendingId(null)
      setFailedActionId(null)
      await onInvalidate()
    },
    onError: (mutationError, action) => {
      setPendingId(null)
      setFailedActionId(action.id)
      setError(
        mutationError instanceof Error ? mutationError.message : 'Action failed — retry needed',
      )
    },
  })

  if (actions.length === 0) return null

  return (
    <div className="shrink-0 border-b border-line bg-panel/30 px-4 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="taste-micro shrink-0">Next</p>
        {actions.map((action) => (
          <Button
            key={action.id}
            size="sm"
            variant={action.destructive ? 'outline' : action.primary ? 'default' : 'outline'}
            disabled={pendingId != null}
            className={cn(action.destructive && 'border-red-300 text-red-800 hover:bg-red-50')}
            onClick={() => {
              if (action.softWarning || action.confirm) {
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
              const last = actions.find((action) => action.id === failedActionId)
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
        title={confirmAction?.confirm?.title ?? confirmAction?.label ?? 'Confirm'}
        description={
          confirmAction?.confirm?.description ??
          (confirmAction?.softWarning
            ? `${confirmAction.softWarning} This does not block close.`
            : (confirmAction?.hint ?? 'Confirm this action.'))
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

function matchedContactDisplayName(contact: MatchedPersonContact): string | null {
  const first = contact.first_initial?.trim()
  const last = contact.last_initial?.trim()
  if (first || last) return [first, last].filter(Boolean).join('')
  return null
}

function phoneSummaryFromMatched(contact: MatchedPersonContact): string | null {
  if (!contact.phones?.length) return null
  return contact.phones.map((phone) => `${phone.type}: ${phone.number}`).join(' · ')
}

/** Requester contact for Details / Inbox Overview — DROP after match, else intake contact. */
export function RequesterContactSection({
  intakeSource,
  displayLabel,
  requestContact,
  matching,
  dropPreMatch = false,
  compact = false,
}: {
  intakeSource: string
  displayLabel?: string | null
  requestContact?: RequesterContact | null
  matching?: MatchingResultDetail | null
  dropPreMatch?: boolean
  compact?: boolean
}) {
  const isDrop = intakeSource === 'drop'
  const matched = matching?.matched_contacts ?? []
  const matchStatus = matching?.matched_contacts_status
  const primaryMatched = matched[0] ?? null

  const rows: { label: string; value: string }[] = []

  if (isDrop) {
    if (dropPreMatch || matching == null) {
      return (
        <div className={cn('space-y-1.5', compact ? 'text-[0.7rem]' : 'text-xs')}>
          <p className="taste-micro">Requester contact</p>
          <p className="text-mute">
            Available after a person match (DROP does not include requester contact at
            intake).
          </p>
        </div>
      )
    }
    if (matchStatus === 'unavailable') {
      return (
        <div className={cn('space-y-1.5', compact ? 'text-[0.7rem]' : 'text-xs')}>
          <p className="taste-micro">Requester contact</p>
          <p className="text-mute">Matched person details unavailable right now.</p>
        </div>
      )
    }
    if (matched.length === 0 || matching.match_count <= 0) {
      return (
        <div className={cn('space-y-1.5', compact ? 'text-[0.7rem]' : 'text-xs')}>
          <p className="taste-micro">Requester contact</p>
          <p className="text-mute">No matched person contact on file yet.</p>
        </div>
      )
    }
    const initials = matchedContactDisplayName(primaryMatched!)
    if (initials) rows.push({ label: 'Initials', value: initials })
    if (primaryMatched?.state) rows.push({ label: 'State', value: primaryMatched.state })
    if (primaryMatched?.email) rows.push({ label: 'Email', value: primaryMatched.email })
    const phones = phoneSummaryFromMatched(primaryMatched!)
    if (phones) rows.push({ label: 'Phone', value: phones })
    if (primaryMatched?.dob) rows.push({ label: 'DOB', value: primaryMatched.dob })
    if (matched.length > 1) {
      rows.push({ label: 'Persons', value: `${matched.length} matched` })
    }
  } else {
    const name = requestContact?.name?.trim() || displayLabel?.trim() || null
    const email = requestContact?.email?.trim() || null
    const phone = requestContact?.phone?.trim() || null
    if (name) rows.push({ label: 'Name', value: name })
    if (email) rows.push({ label: 'Email', value: email })
    if (phone) rows.push({ label: 'Phone', value: phone })
    if (rows.length === 0) {
      return (
        <div className={cn('space-y-1.5', compact ? 'text-[0.7rem]' : 'text-xs')}>
          <p className="taste-micro">Requester contact</p>
          <p className="text-mute">No contact on file for this intake.</p>
        </div>
      )
    }
  }

  return (
    <div className={cn('space-y-1.5', compact ? 'text-[0.7rem]' : 'text-xs')}>
      <p className="taste-micro">Requester contact</p>
      <dl
        className={cn(
          'grid gap-x-4 gap-y-2',
          compact ? 'grid-cols-2 sm:grid-cols-3' : 'grid-cols-1 sm:grid-cols-2',
        )}
      >
        {rows.map((row) => (
          <div key={row.label} className="min-w-0">
            <dt className="text-[0.6rem] text-mute">{row.label}</dt>
            <dd
              className={cn(
                'mt-0.5 text-ink',
                row.label === 'Email' || row.label === 'Phone' || row.label === 'Initials'
                  ? 'break-all'
                  : 'truncate',
                row.label === 'Initials' || row.label === 'State' ? 'font-mono' : null,
              )}
              title={row.value}
            >
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** Request / requester facts — shown as the Details tab (not a side rail). */
function RequestDetailsPanel({
  requestId,
  intakeSource,
  displayLabel,
  requestContact,
  requestorState,
  identityStatus,
  matching,
  dropStatusCode = null,
  dropStatusIsRecommended = false,
  dropPreMatch = false,
}: {
  requestId: string
  intakeSource: string
  displayLabel?: string | null
  requestContact?: RequesterContact | null
  requestorState?: string | null
  identityStatus?: string | null
  matching?: MatchingResultDetail | null
  dropStatusCode?: number | null
  dropStatusIsRecommended?: boolean
  dropPreMatch?: boolean
}) {
  const channel = SOURCE_LABELS[intakeSource] ?? intakeSource
  const isDrop = intakeSource === 'drop'

  const rows: { label: string; value: string }[] = []
  rows.push({
    label: 'Display',
    value: requestDetailHeaderLabel(requestId, intakeSource, displayLabel),
  })
  rows.push({ label: 'Request id', value: requestId })
  rows.push({ label: 'Channel', value: channel })
  if (isDrop) {
    rows.push({
      label: 'CA DROP status',
      value:
        dropStatusCode != null
          ? `${dropResponseStatusLabel(dropStatusCode)}${
              dropStatusIsRecommended ? ' (recommended)' : ''
            }`
          : 'Pending',
    })
  }
  if (!(isDrop && dropPreMatch)) {
    rows.push({
      label: 'State',
      value: requestorState ?? matching?.requestor_state ?? '—',
    })
    rows.push({
      label: 'Identity verification',
      value: identityStatus ?? 'none recorded',
    })
    if (matching) {
      rows.push({ label: 'Matching results', value: matchingResultsLabel(matching) })
      rows.push({
        label: 'Matching status',
        value: matchingStatusLabel(matching.review_status),
      })
    }
  }

  return (
    <div className="space-y-5 text-xs">
      <RequesterContactSection
        intakeSource={intakeSource}
        displayLabel={displayLabel}
        requestContact={requestContact}
        matching={matching}
        dropPreMatch={dropPreMatch}
      />
      <div className="space-y-3">
        <p className="taste-micro">Request details</p>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2.5 sm:grid-cols-2">
          {rows.map((row) => (
            <div key={row.label} className="min-w-0">
              <dt className="text-[0.65rem] text-mute">{row.label}</dt>
              <dd
                className={cn(
                  'mt-0.5 text-ink',
                  row.label === 'Request id' || row.label === 'Display' || row.label === 'State'
                    ? 'font-mono text-[0.7rem]'
                    : null,
                  row.label === 'Identity verification' ? 'capitalize' : null,
                )}
              >
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}

type ActivityFilter = 'all' | 'notes' | 'system'

const HUMAN_ACTIVITY_KINDS = new Set(['comment', 'assignment', 'escalation'])

function isHumanActivityKind(kind: string): boolean {
  return HUMAN_ACTIVITY_KINDS.has(kind.trim().toLowerCase())
}

function activityKindLabel(kind: string): string | null {
  switch (kind.trim().toLowerCase()) {
    case 'comment':
      return 'Note'
    case 'assignment':
      return 'Assignment'
    case 'escalation':
      return 'Assignment to legal'
    case 'approval':
      return 'Approval'
    case 'stage':
      return 'Stage'
    case 'audit':
      return null
    default:
      return null
  }
}

/** Humanize dotted reason keys that may appear in timeline summaries. */
function humanizeActivitySummary(summary: string): string {
  return summary.replace(
    /\b[\w]+(?:\.[\w]+)+\b/g,
    (match) => actionReasonLabel(match),
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
  const [filter, setFilter] = useState<ActivityFilter>('all')
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

  const filtered = entries.filter((entry) => {
    const human = isHumanActivityKind(entry.kind)
    if (filter === 'notes') return human
    if (filter === 'system') return !human
    return true
  })

  const filters: { id: ActivityFilter; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'notes', label: 'Notes & assignment' },
    { id: 'system', label: 'System' },
  ]

  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="taste-micro">Activity</p>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Activity filter">
          {filters.map((item) => (
            <button
              key={item.id}
              type="button"
              className={cn(
                'rounded border px-2 py-0.5 text-[0.65rem] transition-colors',
                filter === item.id
                  ? 'border-habeas-navy bg-habeas-navy text-white'
                  : 'border-line bg-paper text-ink-soft hover:border-ink/30',
              )}
              aria-pressed={filter === item.id}
              onClick={() => setFilter(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {isPending ? <SkeletonLines lines={4} /> : null}
      {!isPending && filtered.length === 0 ? (
        <p className="text-xs text-ink-soft">
          {entries.length === 0 ? 'No activity yet.' : 'No matching activity for this filter.'}
        </p>
      ) : null}

      <ol className="space-y-1.5">
        {filtered.map((entry, index) => {
          const human = isHumanActivityKind(entry.kind)
          const kindLabel = activityKindLabel(entry.kind)
          const summary = humanizeActivitySummary(entry.summary)

          if (!human) {
            return (
              <li
                key={`${entry.at}-${entry.kind}-${index}`}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1 text-xs text-mute"
              >
                <time className="shrink-0 tabular-nums text-[0.65rem]">
                  {formatTimestamp(entry.at)}
                </time>
                <span className="min-w-0 text-ink-soft">{summary}</span>
              </li>
            )
          }

          return (
            <li
              key={`${entry.at}-${entry.kind}-${index}`}
              className="rounded-lg border border-line/80 bg-paper/70 px-3 py-2 text-xs"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                  {kindLabel ? (
                    <Badge variant="wait" className="normal-case tracking-normal">
                      {kindLabel}
                    </Badge>
                  ) : null}
                  <span className="font-medium text-ink">
                    {entry.actor?.trim() || 'Operator'}
                  </span>
                </div>
                <time className="shrink-0 tabular-nums text-[0.65rem] text-mute">
                  {formatTimestamp(entry.at)}
                </time>
              </div>
              <p className="mt-1.5 whitespace-pre-wrap text-ink">{summary}</p>
            </li>
          )
        })}
      </ol>

      <div className="space-y-2 border-t border-line pt-3">
        <p className="taste-micro">Add a note</p>
        <textarea
          className="min-h-[4.5rem] w-full rounded-lg border border-line bg-paper-raised px-3 py-2 text-xs text-ink"
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          maxLength={2000}
          placeholder="Add a note…"
          aria-label="Add a note"
        />
        <Button
          type="button"
          size="sm"
          disabled={comment.trim().length === 0 || commentMutation.isPending}
          onClick={() => commentMutation.mutate()}
        >
          {commentMutation.isPending ? 'Posting…' : 'Post note'}
        </Button>
        {error ? <p className="text-xs text-red-700">{error}</p> : null}
      </div>
    </div>
  )
}

/** Legal kickoff (R11/KD6) + Access identity-comment gate (R13/KTD6) on Fulfillment tab. */
function FulfillmentGateControls({
  requestId,
  rows,
  onInvalidate,
}: {
  requestId: string
  rows: WorkbenchVerticalRow[]
  onInvalidate: () => Promise<void>
}) {
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)

  const needsIdentity = rows.some(
    (row) => row.identity_required && row.identity_verified !== true,
  )
  const kickoffCandidates = rows.filter(
    (row) => row.actionable && !row.kicked_off && row.disposition_status != null,
  )

  const identityMutation = useMutation({
    mutationFn: () =>
      postIdentityVerification(requestId, { status: 'verified', method: 'manual', notes }),
    onSuccess: async () => {
      setError(null)
      setNotes('')
      await onInvalidate()
    },
    onError: (err) => setError(err instanceof Error ? err.message : 'Identity verification failed'),
  })

  const kickoffMutation = useMutation({
    mutationFn: (vertical: string) => postFulfillmentKickoff(requestId, { vertical }),
    onSuccess: async () => {
      setError(null)
      await onInvalidate()
    },
    onError: (err) => setError(err instanceof Error ? err.message : 'Kickoff failed'),
  })

  if (!needsIdentity && kickoffCandidates.length === 0) return null

  return (
    <div className="space-y-3 rounded-lg border border-line/80 bg-panel/30 p-3">
      <p className="taste-micro">Fulfillment gate</p>
      {needsIdentity ? (
        <div className="space-y-1.5">
          <p className="text-[0.7rem] text-ink-soft">
            Access pack/notice requires identity verification with a required comment (KTD6).
          </p>
          <textarea
            className="min-h-[3rem] w-full rounded-lg border border-line bg-paper-raised px-3 py-2 text-xs text-ink"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            maxLength={2000}
            placeholder="Verification method / comment (required)…"
            aria-label="Identity verification comment"
          />
          <Button
            type="button"
            size="sm"
            disabled={notes.trim().length === 0 || identityMutation.isPending}
            onClick={() => identityMutation.mutate()}
          >
            {identityMutation.isPending ? 'Verifying…' : 'Mark identity verified'}
          </Button>
        </div>
      ) : null}
      {kickoffCandidates.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="taste-micro shrink-0">Kickoff</p>
          {kickoffCandidates.map((row) => (
            <Button
              key={row.vertical}
              type="button"
              size="sm"
              variant="outline"
              disabled={
                (row.identity_required && row.identity_verified !== true) ||
                kickoffMutation.isPending
              }
              title={row.blocker ?? undefined}
              onClick={() => kickoffMutation.mutate(row.vertical)}
            >
              {kickoffMutation.isPending && kickoffMutation.variables === row.vertical
                ? 'Starting…'
                : `Start fulfillment — ${row.label}`}
            </Button>
          ))}
        </div>
      ) : null}
      {error ? <p className="text-xs text-red-700">{error}</p> : null}
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
  const [matchingActionError, setMatchingActionError] = useState<string | null>(null)

  useEffect(() => {
    setTab(defaultTab)
  }, [requestId, defaultTab])

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

  const workbenchQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey-workbench'],
    queryFn: () => getRequestJourneyWorkbench(requestId),
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

  const matchingDispositionMutation = useMutation({
    mutationFn: async ({
      action,
      responseStatus,
    }: {
      action: 'promote' | 'decline'
      responseStatus?: DropResponseStatusCode
    }) => {
      if (action === 'promote') {
        return postDropMatchingResultPromote(requestId, {
          response_status: responseStatus,
        })
      }
      return postDropMatchingResultDecline(requestId)
    },
    onSuccess: async () => {
      setMatchingActionError(null)
      await invalidateAll()
    },
    onError: (mutationError) => {
      setMatchingActionError(
        mutationError instanceof Error ? mutationError.message : 'Matching action failed',
      )
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
  const workbench = workbenchQuery.data
  const railSteps = workbench ? workbenchRailSteps(workbench.stages) : coarseSteps

  const assignmentToLegal = isAssignmentToLegalContext(attentionItem)
  const canMatchingDisposition =
    matching != null &&
    matching.review_status === 'pending' &&
    Boolean(matching.approval_id) &&
    ((legalAdmin && assignmentToLegal) || (role === 'data_owner' && !legalAdmin))

  const dropPreMatch =
    intakeSource === 'drop' &&
    matching == null &&
    (journey?.current_stage === 'received' ||
      journey?.current_stage === 'download' ||
      journey?.current_stage === 'land' ||
      journey?.current_stage === 'promote' ||
      journey?.current_stage === 'match')

  const dropResolved =
    intakeSource === 'drop'
      ? resolveDropStatusCode({
          journey,
          matching,
          attentionItem,
        })
      : null
  const dropStatusCode = dropResolved?.code ?? null
  const dropStatusIsRecommended = dropResolved?.isRecommended ?? false

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

  const currentCoarse =
    coarseSteps.find((step) => step.status === 'running' || step.status === 'waiting') ??
    coarseSteps.find((step) => step.status === 'failed') ??
    coarseSteps[coarseSteps.length - 1]

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <RequestStageActionBar actions={stageActions} onInvalidate={invalidateAll} />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {/* KTD2 four-stage rail (Ingest → Matching → Fulfillment → Notice) + vertical clusters (R1–R3) */}
        <div
          className={cn(
            'shrink-0 space-y-2 overflow-x-auto border-b border-line px-4',
            variant === 'overlay' ? 'py-2' : 'py-3',
          )}
        >
          <div className="flex items-center justify-between gap-2">
            {workbenchQuery.isPending && !workbench ? (
              <p className="text-[0.7rem] text-mute">Loading stage rail…</p>
            ) : (
              <RunTimeline
                steps={railSteps}
                orientation="horizontal"
                emptyMessage={
                  currentCoarse?.label
                    ? `Stage: ${currentCoarse.label}`
                    : 'No stage rail.'
                }
              />
            )}
            {workbench?.split_posture ? (
              <Badge variant="wait" className="shrink-0 normal-case tracking-normal">
                Matching + Fulfillment in progress
              </Badge>
            ) : null}
          </div>
          {workbench && (workbench.matching_cluster.length > 0 || workbench.fulfillment_cluster.length > 0) ? (
            <div className="flex flex-wrap gap-3 pt-1">
              <VerticalClusterList
                title="Matching"
                rows={workbench.matching_cluster}
                statusOf={(row) => row.matching_status}
                onSelect={() => setTab('matching')}
              />
              <VerticalClusterList
                title="Fulfillment"
                rows={workbench.fulfillment_cluster}
                statusOf={(row) => row.fulfillment_status}
                onSelect={() => setTab('fulfillment')}
              />
            </div>
          ) : null}
        </div>

        <Tabs
          value={tab}
          onValueChange={(value) => setTab(value as RequestDetailTab)}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <div className="shrink-0 border-b border-line px-4 py-2">
            <TabsList className="h-9 w-full justify-start gap-1 bg-canvas p-1">
              <TabsTrigger value="details" className="h-7 px-3">
                Details
              </TabsTrigger>
              <TabsTrigger value="fulfillment" className="h-7 px-3">
                Fulfillment
              </TabsTrigger>
              <TabsTrigger value="matching" className="h-7 px-3">
                Matching
              </TabsTrigger>
              <TabsTrigger value="activity" className="h-7 px-3">
                Activity
              </TabsTrigger>
            </TabsList>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <TabsContent value="details" className="mt-0 px-4 py-4">
              <RequestDetailsPanel
                requestId={requestId}
                intakeSource={intakeSource}
                displayLabel={displayLabel}
                requestContact={requestQuery.data?.contact}
                requestorState={requestQuery.data?.requestor_state}
                identityStatus={identityQuery.data?.status}
                matching={matching}
                dropStatusCode={dropStatusCode}
                dropStatusIsRecommended={dropStatusIsRecommended}
                dropPreMatch={dropPreMatch}
              />
            </TabsContent>
            <TabsContent value="fulfillment" className="mt-0 px-4 py-4">
              <div className="space-y-4">
                {workbench && (isSuperAdmin || isAdmin || legalAdmin) ? (
                  <FulfillmentGateControls
                    requestId={requestId}
                    rows={workbench.fulfillment_cluster}
                    onInvalidate={invalidateAll}
                  />
                ) : null}
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
                <div className="space-y-1">
                  <p className="taste-micro">Identity verification</p>
                  {identityQuery.data ? (
                    <p className="text-xs text-ink-soft">
                      Status:{' '}
                      <span className="capitalize text-ink">{identityQuery.data.status}</span>
                      <span className="text-mute">
                        {' '}
                        · {formatTimestamp(identityQuery.data.verified_at)}
                      </span>
                      {identityQuery.data.method ? (
                        <span className="text-mute">
                          {' '}
                          · {identityQuery.data.method}
                        </span>
                      ) : null}
                    </p>
                  ) : (
                    <p className="text-xs text-mute">
                      None recorded — use Identity verified in stage actions when ready.
                    </p>
                  )}
                </div>
                <AccessDeliveryEmailCard requestId={requestId} />
              </div>
            </TabsContent>
            <TabsContent value="matching" className="mt-0 px-4 py-4">
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
                actionPending={matchingDispositionMutation.isPending}
                actionError={matchingActionError}
                hideActions={!canMatchingDisposition}
                layout="tabs"
                compact
                onPromote={(responseStatus) =>
                  matchingDispositionMutation.mutate({
                    action: 'promote',
                    responseStatus,
                  })
                }
                onDecline={() => matchingDispositionMutation.mutate({ action: 'decline' })}
              />
            </TabsContent>
            <TabsContent value="activity" className="mt-0">
              <ActivityPanel
                requestId={requestId}
                entries={timelineQuery.data?.entries ?? []}
                isPending={timelineQuery.isPending && !timelineQuery.data}
              />
            </TabsContent>
          </div>
        </Tabs>

        {variant === 'overlay' ? (
          <div className="flex shrink-0 flex-wrap gap-2 border-t border-line px-4 py-2">
            <Link
              to="/requests/$requestId"
              params={{ requestId }}
              className="text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline"
            >
              Open full page →
            </Link>
            {isSuperAdmin ? (
              <Link
                to="/ops/runs"
                search={{ request_id: requestId }}
                className="text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline"
              >
                Runs for request →
              </Link>
            ) : null}
          </div>
        ) : null}
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

  // Shared query keys with RequestDetailBody — cache hit, no extra network when body loads.
  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey'],
    queryFn: () => getRequestJourney(requestId!),
    enabled: open && Boolean(requestId),
    placeholderData: (previous) => previous,
  })

  const matchingQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop', 'matching-results', requestId],
    queryFn: () => fetchMatchingDetailOptional(requestId!),
    enabled: open && Boolean(requestId),
    placeholderData: (previous) => previous,
  })

  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention', 'overlay', requestId],
    queryFn: async () => {
      const response = await getNeedsAttention(200)
      return response.items.find((item) => item.request_id === requestId)
    },
    enabled: open && Boolean(requestId),
    staleTime: 10_000,
  })

  const intakeSource =
    journeyQuery.data?.intake_source ?? seedRequest?.intake_source ?? 'manual'
  const dropResolved =
    intakeSource === 'drop'
      ? resolveDropStatusCode({
          journey: journeyQuery.data,
          matching: matchingQuery.data,
          attentionItem: attentionQuery.data,
        })
      : null
  const dropStatusCode = dropResolved?.code ?? null
  const dropStatusIsRecommended = dropResolved?.isRecommended ?? false

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={contentRef}
        className={cn(
          'flex h-[96vh] max-h-[96vh] w-[96vw] max-w-[96vw] flex-col gap-0 overflow-hidden p-0',
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
        <DialogHeader className="shrink-0 space-y-1 border-b border-line px-4 py-2.5 pr-12">
          <div className="flex flex-wrap items-center gap-2">
            <DialogTitle className="font-mono text-sm">
              {requestId
                ? requestDetailHeaderLabel(
                    requestId,
                    intakeSource,
                    seedRequest?.display_label,
                  )
                : '—'}
            </DialogTitle>
            {intakeSource === 'drop' && dropStatusCode != null ? (
              <Badge
                variant="run"
                className="normal-case tracking-normal"
                title={
                  dropStatusIsRecommended
                    ? 'Recommended CA DROP status from matching'
                    : 'CA DROP response status'
                }
              >
                CA DROP · {dropResponseStatusLabel(dropStatusCode)}
                {dropStatusIsRecommended ? ' (recommended)' : ''}
              </Badge>
            ) : intakeSource === 'drop' ? (
              <Badge variant="wait" className="normal-case tracking-normal">
                CA DROP · status pending
              </Badge>
            ) : null}
          </div>
          <DialogDescription className="sr-only">
            Request detail overlay — fulfillment, matching, and activity.
          </DialogDescription>
        </DialogHeader>
        {requestId && open ? (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <RequestDetailBody
              requestId={requestId}
              variant="overlay"
              defaultTab="fulfillment"
              seedRequest={seedRequest}
            />
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
