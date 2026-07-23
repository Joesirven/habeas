import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  AccessHandoffPanel,
  buildAccessDeliveryDraft,
  DropResponseStatusPicker,
  MatchingReviewPanel,
} from '@/components/requests/RequestTriageDialog'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
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
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useMe } from '@/lib/auth'
import {
  getDropMatchingResultDetail,
  getFulfillmentArtifact,
  getLegalNeedsAttention,
  getNeedsAttention,
  getRequestComments,
  getRequestJourney,
  patchAccessDeliveryStatus,
  postDropMatchingResultDecline,
  postDropMatchingResultPromote,
  postDropWorkflowAssign,
  postDropWorkflowEscalate,
  postRequestComment,
  postNoticeApprove,
  postTriageBulkReject,
  postTriageSendToMatching,
  suggestedDropResponseStatus,
  type DropResponseStatusCode,
  type JourneyStage,
  type MatchingResultDetail,
  type NeedsAttentionItem,
} from '@/lib/api'
import { cn } from '@/lib/utils'

function recommendedStatusFromItem(
  item: NeedsAttentionItem,
  matching?: MatchingResultDetail | null,
): DropResponseStatusCode {
  const fromApi =
    matching?.recommended_response_status ?? item.recommended_response_status
  if (fromApi === 3 || fromApi === 4 || fromApi === 5) return fromApi
  return suggestedDropResponseStatus(
    matching?.match_type ?? item.match_type,
    matching?.match_count ?? item.match_count,
  )
}

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

/** Mirrors admin-api APPROACHING_SLA_THRESHOLD_HOURS.matching_review */
const MATCHING_REVIEW_SLA_HOURS = 48
/** Within this window of due, treat as “due soon”. */
const DUE_SOON_HOURS = 12

/** Inbox message kind — orthogonal to match result type. */
type InboxKind =
  | 'all'
  | 'matching'
  | 'triage'
  | 'escalations'
  | 'delivery'
  | 'notice'
  | 'communications'
  | 'pending_tasks'
type MatchFilter = 'all' | 'single_match' | 'multi_match' | 'not_found' | 'unknown'
type DueFilter = 'all' | 'overdue' | 'due_soon' | 'on_track'

const OPS_INBOX_KIND_TABS: { value: InboxKind; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'matching', label: 'Matching' },
  { value: 'triage', label: 'Triage' },
  { value: 'escalations', label: 'Escalations' },
  { value: 'delivery', label: 'Delivery' },
  { value: 'notice', label: 'Notice' },
  { value: 'communications', label: 'Comms' },
  { value: 'pending_tasks', label: 'Tasks' },
]

/** Legal case queue — no Matching / Comms / All (matching stays on data-owner My work). */
const LEGAL_INBOX_KIND_TABS: { value: InboxKind; label: string }[] = [
  { value: 'triage', label: 'Triage' },
  { value: 'escalations', label: 'Escalations' },
  { value: 'notice', label: 'Notice' },
  { value: 'delivery', label: 'Delivery' },
  { value: 'pending_tasks', label: 'Tasks' },
]

/** Data-owner / employee queue — matching review + assigned Tasks. */
const DATA_OWNER_INBOX_KIND_TABS: { value: InboxKind; label: string }[] = [
  { value: 'matching', label: 'Matching' },
  { value: 'pending_tasks', label: 'Tasks' },
]

function isTriageItem(item: NeedsAttentionItem): boolean {
  return (
    item.kind === 'triage' ||
    item.assignment?.kind === 'triage' ||
    item.current_stage === 'triage'
  )
}

function isEscalationItem(item: NeedsAttentionItem): boolean {
  return (
    item.kind === 'escalations' ||
    item.assignment?.kind === 'escalate'
  )
}

function isMatchingItem(item: NeedsAttentionItem): boolean {
  if (isTriageItem(item) || isEscalationItem(item)) return false
  return (
    item.kind === 'matching' ||
    item.reason === 'matching.review' ||
    item.match_type != null ||
    item.current_stage === 'review'
  )
}

function isDeliveryItem(item: NeedsAttentionItem): boolean {
  return (
    item.kind === 'delivery' ||
    item.reason === 'access.delivery' ||
    item.reason === 'delivery.confirm' ||
    item.current_stage === 'delivery'
  )
}

function isNoticeItem(item: NeedsAttentionItem): boolean {
  return (
    item.kind === 'notice' ||
    item.reason === 'notice.review' ||
    item.current_stage === 'notice'
  )
}

function isCommsItem(item: NeedsAttentionItem): boolean {
  return (
    item.reason.startsWith('comms.') ||
    item.reason.includes('communication') ||
    item.current_stage === 'comms'
  )
}

function isPendingTaskFor(item: NeedsAttentionItem, email: string | undefined): boolean {
  if (!email) return false
  const assignee = item.assignment?.assignee_identity?.trim().toLowerCase()
  return Boolean(assignee && assignee === email.trim().toLowerCase())
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function formatRelativeTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  const diffMs = Date.now() - date.getTime()
  if (Number.isNaN(diffMs)) return '—'

  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return 'just now'

  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`

  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`

  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`

  return date.toLocaleDateString()
}

function reasonLabel(reason: string): string {
  return reason.replaceAll('.', ' · ').replaceAll('_', ' ')
}

function matchTypeLabel(matchType: string | null | undefined): string {
  if (!matchType) return 'No match data'
  return matchType.replaceAll('_', ' ')
}

function inboxItemTitle(item: NeedsAttentionItem): string {
  if (isTriageItem(item)) {
    const state = item.requestor_state?.trim()
    return state ? `Triage hold · ${state}` : 'Triage hold · condition route'
  }
  if (isEscalationItem(item)) return 'Escalated to Legal'
  if (isDeliveryItem(item)) return 'Access pack ready · copy URL'
  if (isNoticeItem(item)) return 'Notice review before Wed upload'
  if (isCommsItem(item)) return 'Requester communications'
  if (isMatchingItem(item)) {
    return `Matching review · ${matchTypeLabel(item.match_type)}`
  }
  return reasonLabel(item.reason)
}

function journeySegmentClass(status: JourneyStage['status']): string {
  if (status === 'complete') return 'bg-emerald-600'
  if (status === 'failed') return 'bg-red-600'
  if (status === 'waiting' || status === 'in_progress') return 'bg-amber-500'
  if (status === 'skipped') return 'bg-mute/50'
  return 'bg-line'
}

function matchTypeBadgeVariant(
  matchType: string | null | undefined,
): 'default' | 'ok' | 'fail' | 'wait' | 'run' {
  if (matchType === 'single_match') return 'wait'
  if (matchType === 'multi_match') return 'fail'
  if (matchType === 'not_found') return 'default'
  return 'default'
}

function JourneyProgressBar({ stages }: { stages: JourneyStage[] }) {
  if (stages.length === 0) return null
  const activeIdx = stages.findIndex(
    (stage) =>
      stage.status === 'in_progress' ||
      stage.status === 'waiting' ||
      stage.status === 'failed',
  )

  return (
    <div className="space-y-1.5" role="group" aria-label="Request journey">
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-canvas ring-1 ring-line">
        {stages.map((stage) => (
          <div
            key={stage.stage}
            className={cn(
              'h-full min-w-[3px] flex-1',
              journeySegmentClass(stage.status),
            )}
            title={`${stage.label}: ${stage.status.replaceAll('_', ' ')}${
              stage.blocker ? ` — ${stage.blocker}` : ''
            }`}
          />
        ))}
      </div>
      <div className="flex gap-0.5">
        {stages.map((stage, index) => (
          <span
            key={stage.stage}
            className={cn(
              'min-w-0 flex-1 truncate text-center text-[0.55rem] leading-tight',
              index === activeIdx ||
                stage.status === 'in_progress' ||
                stage.status === 'waiting'
                ? 'font-medium text-ink'
                : 'text-mute',
            )}
            title={stage.blocker ?? undefined}
          >
            {stage.label}
          </span>
        ))}
      </div>
    </div>
  )
}

function IconCheck({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden
    >
      <path d="M3 8.5 6 11.5 13 4.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconX({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden
    >
      <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
    </svg>
  )
}

function IconCopy({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden
    >
      <rect x="5.5" y="5.5" width="8" height="8" rx="1" />
      <path d="M10.5 5.5V4a1.5 1.5 0 00-1.5-1.5H4A1.5 1.5 0 002.5 4v5A1.5 1.5 0 004 10.5h1.5" />
    </svg>
  )
}

function IconMail({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden
    >
      <rect x="2" y="4" width="12" height="9" rx="1" />
      <path d="M2 5.5l6 4 6-4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconExternal({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden
    >
      <path d="M10 2h4v4M14 2L7 9M6 3H3a1 1 0 00-1 1v9a1 1 0 001 1h9a1 1 0 001-1v-3" />
    </svg>
  )
}

function emailInitials(email: string | null | undefined): string {
  if (!email) return '?'
  const local = email.split('@')[0] ?? email
  const parts = local.split(/[._+-]/).filter(Boolean)
  if (parts.length >= 2) {
    return `${parts[0]![0] ?? ''}${parts[1]![0] ?? ''}`.toUpperCase()
  }
  return local.slice(0, 2).toUpperCase() || '?'
}

/** Deterministic due from matching.review SLA + request anchors (id for stable label). */
function deriveDueAt(item: NeedsAttentionItem): Date | null {
  const anchor = item.requested_at ?? item.received_at
  if (!anchor) return null
  const start = new Date(anchor)
  if (Number.isNaN(start.getTime())) return null
  return new Date(start.getTime() + MATCHING_REVIEW_SLA_HOURS * 60 * 60 * 1000)
}

type DueBucket = 'overdue' | 'due_soon' | 'on_track' | 'unknown'

function dueBucket(item: NeedsAttentionItem, now = Date.now()): DueBucket {
  const due = deriveDueAt(item)
  if (!due) return 'unknown'
  const msLeft = due.getTime() - now
  if (msLeft < 0) return 'overdue'
  if (msLeft <= DUE_SOON_HOURS * 60 * 60 * 1000) return 'due_soon'
  return 'on_track'
}

function formatDueLabel(item: NeedsAttentionItem): string {
  const due = deriveDueAt(item)
  if (!due) return 'No due date'
  const bucket = dueBucket(item)
  const when = due.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
  if (bucket === 'overdue') return `Overdue · ${when}`
  if (bucket === 'due_soon') return `Due soon · ${when}`
  return `Due ${when}`
}

function FilterChip({
  active,
  label,
  count,
  onClick,
}: {
  active: boolean
  label: string
  count?: number
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[0.7rem] font-medium transition-colors',
        active
          ? 'border-habeas-navy/30 bg-habeas-navy/8 text-habeas-navy'
          : 'border-line bg-paper text-ink-soft hover:border-line hover:text-ink',
      )}
    >
      {label}
      {count != null ? (
        <span
          className={cn(
            'tabular-nums',
            active ? 'text-habeas-navy/80' : 'text-mute',
          )}
        >
          {count}
        </span>
      ) : null}
    </button>
  )
}

function AssigneeAvatarPicker({
  currentEmail,
  candidates,
  disabled,
  pending,
  error,
  onAssign,
}: {
  currentEmail: string | null | undefined
  candidates: string[]
  disabled: boolean
  pending: boolean
  error: string | null
  onAssign: (email: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [customEmail, setCustomEmail] = useState('')
  const assigned = Boolean(currentEmail)

  return (
    <div className="flex items-center gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            disabled={disabled || pending}
            className={cn(
              'inline-flex items-center gap-2 rounded-md border border-line bg-paper px-1.5 py-1 text-left transition-colors',
              disabled
                ? 'cursor-default opacity-70'
                : 'hover:border-habeas-navy/30 hover:bg-habeas-navy/[0.04]',
            )}
            aria-label={assigned ? `Assigned to ${currentEmail}` : 'Assign reviewer'}
          >
            <Avatar className="h-7 w-7">
              <AvatarFallback>{emailInitials(currentEmail)}</AvatarFallback>
            </Avatar>
            <span className="min-w-0 max-w-[10rem]">
              <span className="block text-[0.6rem] text-mute">Assignee</span>
              <span className="block truncate text-[0.7rem] font-medium text-ink">
                {currentEmail ?? 'Unassigned'}
              </span>
            </span>
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-2" align="start">
          <p className="px-1.5 pb-1.5 text-[0.65rem] text-mute">
            Pick a reviewer or enter an email
          </p>
          <ul className="max-h-40 space-y-0.5 overflow-y-auto">
            {candidates.map((email) => {
              const selected = email === currentEmail
              return (
                <li key={email}>
                  <button
                    type="button"
                    className={cn(
                      'flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-xs',
                      selected
                        ? 'bg-habeas-navy/10 text-habeas-navy'
                        : 'hover:bg-panel/60',
                    )}
                    disabled={pending}
                    onClick={() => {
                      onAssign(email)
                      setOpen(false)
                    }}
                  >
                    <Avatar className="h-6 w-6">
                      <AvatarFallback className="text-[0.55rem]">
                        {emailInitials(email)}
                      </AvatarFallback>
                    </Avatar>
                    <span className="min-w-0 truncate">{email}</span>
                  </button>
                </li>
              )
            })}
            {candidates.length === 0 ? (
              <li className="px-1.5 py-2 text-[0.65rem] text-mute">No known reviewers yet.</li>
            ) : null}
          </ul>
          <div className="mt-2 flex gap-1.5 border-t border-line pt-2">
            <input
              className="min-w-0 flex-1 rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
              value={customEmail}
              onChange={(event) => setCustomEmail(event.target.value)}
              placeholder="reviewer@habeas.com"
              aria-label="Assignee email"
              onKeyDown={(event) => {
                if (event.key === 'Enter' && customEmail.trim()) {
                  onAssign(customEmail.trim())
                  setCustomEmail('')
                  setOpen(false)
                }
              }}
            />
            <Button
              size="sm"
              disabled={pending || customEmail.trim().length === 0}
              onClick={() => {
                onAssign(customEmail.trim())
                setCustomEmail('')
                setOpen(false)
              }}
            >
              {pending ? '…' : 'Assign'}
            </Button>
          </div>
          {error ? <p className="mt-1.5 px-0.5 text-[0.65rem] text-red-700">{error}</p> : null}
        </PopoverContent>
      </Popover>
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

function InboxReviewPane({
  item,
  canReviewActions,
  assigneeCandidates,
  legalPersona = false,
  onBackToQueue,
}: {
  item: NeedsAttentionItem
  canReviewActions: boolean
  assigneeCandidates: string[]
  /** Legal case-queue mode — hide DO escalate; resolve escalations via fulfill path. */
  legalPersona?: boolean
  onBackToQueue?: () => void
}) {
  const queryClient = useQueryClient()
  const [actionError, setActionError] = useState<string | null>(null)
  const [commentDraft, setCommentDraft] = useState('')
  const [assignError, setAssignError] = useState<string | null>(null)
  const [commentError, setCommentError] = useState<string | null>(null)
  const [copyNote, setCopyNote] = useState<string | null>(null)
  const [confirmAction, setConfirmAction] = useState<
    | 'fulfill'
    | 'decline'
    | 'escalate'
    | 'triage_reject'
    | 'triage_match'
    | 'notice_approve'
    | null
  >(null)
  const [draftOpen, setDraftOpen] = useState(false)

  const showTriage = isTriageItem(item)
  const showEscalation = isEscalationItem(item)
  const showMatching =
    (isMatchingItem(item) || showEscalation) &&
    !isDeliveryItem(item) &&
    !isNoticeItem(item) &&
    !showTriage &&
    !legalPersona
  const showLegalEscalation = legalPersona && showEscalation
  const showDelivery = isDeliveryItem(item) || item.current_stage === 'fulfill'
  const showNotice = isNoticeItem(item)
  const showComms = isCommsItem(item) && !legalPersona

  const matchingQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop', 'matching-results', item.request_id],
    queryFn: () => fetchMatchingDetailOptional(item.request_id),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
    enabled: showMatching || showLegalEscalation || showDelivery,
  })

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'journey'],
    queryFn: () => getRequestJourney(item.request_id),
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const artifactQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', item.request_id],
    queryFn: () => getFulfillmentArtifact(item.request_id),
    refetchInterval: 15_000,
    retry: false,
    enabled: showDelivery || showComms || item.current_stage === 'fulfill',
  })

  const commentsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'comments'],
    queryFn: () => getRequestComments(item.request_id),
    refetchInterval: 15_000,
  })

  const [fulfillStatus, setFulfillStatus] = useState<DropResponseStatusCode | null>(() =>
    recommendedStatusFromItem(item),
  )
  const suggestedStatus = recommendedStatusFromItem(item, matchingQuery.data)

  const promoteMutation = useMutation({
    mutationFn: (responseStatus: DropResponseStatusCode) =>
      postDropMatchingResultPromote(item.request_id, {
        response_status: responseStatus,
      }),
    onSuccess: async () => {
      setActionError(null)
      setConfirmAction(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Fulfill failed')
    },
  })

  const declineMutation = useMutation({
    mutationFn: () => postDropMatchingResultDecline(item.request_id),
    onSuccess: async () => {
      setActionError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Decline failed')
    },
  })

  const escalateMutation = useMutation({
    mutationFn: () =>
      postDropWorkflowEscalate({
        request_ids: [item.request_id],
        target_role: 'legal',
      }),
    onSuccess: async () => {
      setActionError(null)
      setConfirmAction(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Escalate failed')
    },
  })

  const triageRejectMutation = useMutation({
    mutationFn: () =>
      postTriageBulkReject({
        request_ids: [item.request_id],
        response_status: 2,
      }),
    onSuccess: async () => {
      setActionError(null)
      setConfirmAction(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Triage reject failed')
    },
  })

  const triageMatchMutation = useMutation({
    mutationFn: () =>
      postTriageSendToMatching({ request_ids: [item.request_id] }),
    onSuccess: async () => {
      setActionError(null)
      setConfirmAction(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Send to matching failed')
    },
  })

  const noticeApproveMutation = useMutation({
    mutationFn: () => postNoticeApprove({ request_ids: [item.request_id] }),
    onSuccess: async () => {
      setActionError(null)
      setConfirmAction(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(
        error instanceof Error ? error.message : 'Notice approve failed',
      )
    },
  })

  const assignMutation = useMutation({
    mutationFn: (email: string) =>
      postDropWorkflowAssign({
        request_ids: [item.request_id],
        assignee_identity: email,
        target_role: 'reviewer',
      }),
    onSuccess: async () => {
      setAssignError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setAssignError(error instanceof Error ? error.message : 'Assign failed')
    },
  })

  const commentMutation = useMutation({
    mutationFn: (body: string) => postRequestComment(item.request_id, body),
    onSuccess: async () => {
      setCommentError(null)
      setCommentDraft('')
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'comments'],
      })
    },
    onError: (error) => {
      setCommentError(error instanceof Error ? error.message : 'Comment failed')
    },
  })

  const deliveryMutation = useMutation({
    mutationFn: (status: 'delivered' | 'failed' | 'recalled') =>
      patchAccessDeliveryStatus(item.request_id, { status }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', item.request_id],
      })
    },
  })

  const actionPending =
    promoteMutation.isPending ||
    declineMutation.isPending ||
    escalateMutation.isPending ||
    triageRejectMutation.isPending ||
    triageMatchMutation.isPending ||
    noticeApproveMutation.isPending
  const comments = commentsQuery.data ?? []
  const bucket = dueBucket(item)
  const assignee = item.assignment?.assignee_identity
  const stages = journeyQuery.data?.stages ?? []
  const shareableUrl =
    artifactQuery.data?.shareable_url ?? artifactQuery.data?.fulfillment_artifact_uri ?? ''
  const outboundDraft = buildAccessDeliveryDraft({
    requestId: item.request_id,
    shareableUrl: shareableUrl || '[shareable URL will appear here after fulfillment]',
  })
  const showHandoffTab = showDelivery || showComms
  const showResolveMatching = showMatching || showLegalEscalation
  const primaryTab = showTriage
    ? 'triage'
    : showLegalEscalation
      ? 'comments'
      : showMatching
        ? 'matching'
        : showHandoffTab
          ? 'delivery'
          : showNotice
            ? 'notice'
            : 'comments'

  function copyShareableUrl() {
    if (!shareableUrl) return
    void navigator.clipboard.writeText(shareableUrl).then(() => {
      setCopyNote('Copied URL')
      window.setTimeout(() => setCopyNote(null), 2000)
    })
  }

  return (
    <TooltipProvider delayDuration={250}>
      <div className="flex h-full min-h-0 flex-col">
        <ConfirmActionDialog
          open={confirmAction === 'fulfill'}
          onOpenChange={(open) => {
            if (!open && !actionPending) setConfirmAction(null)
            if (open) setFulfillStatus(suggestedStatus)
          }}
          title="Fulfill this match?"
          description={`Approve matching review for ${item.request_id.slice(0, 8)}… and set the CA DROP status result.`}
          confirmLabel="Fulfill"
          confirming={actionPending && confirmAction === 'fulfill'}
          confirmDisabled={fulfillStatus == null}
          onConfirm={() => {
            if (fulfillStatus != null) promoteMutation.mutate(fulfillStatus)
          }}
        >
          <DropResponseStatusPicker
            value={fulfillStatus}
            onChange={setFulfillStatus}
            disabled={actionPending}
            suggested={suggestedStatus}
          />
        </ConfirmActionDialog>
        <ConfirmActionDialog
          open={confirmAction === 'decline'}
          onOpenChange={(open) => {
            if (!open && !actionPending) setConfirmAction(null)
          }}
          title="Decline matching review?"
          description={`Decline request ${item.request_id.slice(0, 8)}… — it will leave the review queue without fulfillment.`}
          confirmLabel="Decline"
          tone="destructive"
          confirming={actionPending && confirmAction === 'decline'}
          onConfirm={() => declineMutation.mutate()}
        />
        <ConfirmActionDialog
          open={confirmAction === 'escalate'}
          onOpenChange={(open) => {
            if (!open && !actionPending) setConfirmAction(null)
          }}
          title="Escalate to Legal?"
          description={`Send request ${item.request_id.slice(0, 8)}… to Legal Inbox · Escalations. Add a comment first if context is needed.`}
          confirmLabel="Escalate"
          confirming={actionPending && confirmAction === 'escalate'}
          onConfirm={() => escalateMutation.mutate()}
        />
        <ConfirmActionDialog
          open={confirmAction === 'triage_reject'}
          onOpenChange={(open) => {
            if (!open && !actionPending) setConfirmAction(null)
          }}
          title="Bulk reject (Exempted)?"
          description={`Set CA DROP response_status = 2 (Exempted) for ${item.request_id.slice(0, 8)}… and leave Triage.`}
          confirmLabel="Reject as Exempted"
          tone="destructive"
          confirming={actionPending && confirmAction === 'triage_reject'}
          onConfirm={() => triageRejectMutation.mutate()}
        />
        <ConfirmActionDialog
          open={confirmAction === 'triage_match'}
          onOpenChange={(open) => {
            if (!open && !actionPending) setConfirmAction(null)
          }}
          title="Send to matching?"
          description={`Release ${item.request_id.slice(0, 8)}… from Triage and enqueue auto-match for the data owner.`}
          confirmLabel="Send to matching"
          confirming={actionPending && confirmAction === 'triage_match'}
          onConfirm={() => triageMatchMutation.mutate()}
        />
        <ConfirmActionDialog
          open={confirmAction === 'notice_approve'}
          onOpenChange={(open) => {
            if (!open && !actionPending) setConfirmAction(null)
          }}
          title="Approve notice.review?"
          description={`Clear notice review for ${item.request_id.slice(0, 8)}… so it can enter the Wednesday DROP upload batch.`}
          confirmLabel="Approve notice"
          confirming={actionPending && confirmAction === 'notice_approve'}
          onConfirm={() => noticeApproveMutation.mutate()}
        />

        <div className="shrink-0 space-y-2.5 border-b border-line px-4 py-3">
          {onBackToQueue ? (
            <button
              type="button"
              onClick={onBackToQueue}
              className="text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline md:hidden"
            >
              ← Queue
            </button>
          ) : null}

          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                {showTriage ? (
                  <Badge variant="wait" className="normal-case tracking-normal">
                    Triage
                  </Badge>
                ) : showEscalation ? (
                  <Badge variant="fail" className="normal-case tracking-normal">
                    Escalation
                  </Badge>
                ) : item.match_type ? (
                  <Badge
                    variant={matchTypeBadgeVariant(item.match_type)}
                    className="normal-case tracking-normal text-[0.7rem]"
                  >
                    {matchTypeLabel(item.match_type)}
                  </Badge>
                ) : showDelivery ? (
                  <Badge variant="run" className="normal-case tracking-normal">
                    Delivery
                  </Badge>
                ) : showNotice ? (
                  <Badge variant="wait" className="normal-case tracking-normal">
                    Notice review
                  </Badge>
                ) : showComms ? (
                  <Badge variant="default" className="normal-case tracking-normal">
                    Communications
                  </Badge>
                ) : (
                  <span className="text-sm font-medium text-ink">{inboxItemTitle(item)}</span>
                )}
                {(showTriage || showEscalation) && item.requestor_state ? (
                  <Badge variant="default" className="normal-case tracking-normal">
                    {item.requestor_state}
                  </Badge>
                ) : null}
                <Badge
                  variant={
                    bucket === 'overdue' ? 'fail' : bucket === 'due_soon' ? 'wait' : 'default'
                  }
                  className="normal-case tracking-normal"
                >
                  {formatDueLabel(item)}
                </Badge>
              </div>
              <p className="truncate text-[0.65rem] text-mute">{compactMetaLine(item)}</p>
              <p className="font-mono text-[0.6rem] text-mute/80">{item.request_id}</p>
            </div>
            <AssigneeAvatarPicker
              currentEmail={assignee}
              candidates={assigneeCandidates}
              disabled={!canReviewActions}
              pending={assignMutation.isPending}
              error={assignError}
              onAssign={(email) => assignMutation.mutate(email)}
            />
          </div>

          <div className="flex flex-wrap items-center gap-0.5">
            {showTriage && canReviewActions ? (
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-[0.65rem]"
                      disabled={actionPending}
                      onClick={() => setConfirmAction('triage_reject')}
                      aria-label="Reject as Exempted"
                    >
                      Reject 2
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Legal Triage — set DROP status 2 Exempted</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-[0.65rem]"
                      disabled={actionPending}
                      onClick={() => setConfirmAction('triage_match')}
                      aria-label="Send to matching"
                    >
                      Match
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Send to matching — release Triage hold</TooltipContent>
                </Tooltip>
              </>
            ) : null}
            {showNotice && canReviewActions ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-[0.65rem]"
                    disabled={actionPending}
                    onClick={() => setConfirmAction('notice_approve')}
                    aria-label="Approve notice review"
                  >
                    Approve notice
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  Legal Notice — clear notice.review for Wed DROP upload
                </TooltipContent>
              </Tooltip>
            ) : null}
            {(showMatching || showLegalEscalation) && canReviewActions ? (
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 px-0"
                      disabled={actionPending}
                      onClick={() => setConfirmAction('fulfill')}
                      aria-label="Fulfill"
                    >
                      <IconCheck className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {showLegalEscalation
                      ? 'Resolve escalation — set DROP status and release'
                      : 'Fulfill — approve and release to fulfillment'}
                  </TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 px-0"
                      disabled={actionPending}
                      onClick={() => setConfirmAction('decline')}
                      aria-label="Decline"
                    >
                      <IconX className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Decline — leave queue without fulfillment</TooltipContent>
                </Tooltip>
                {showMatching && !legalPersona ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-[0.65rem]"
                        disabled={actionPending}
                        onClick={() => setConfirmAction('escalate')}
                        aria-label="Escalate to Legal"
                      >
                        Legal
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Escalate to Legal Inbox · Escalations</TooltipContent>
                  </Tooltip>
                ) : null}
              </>
            ) : null}
            {(showDelivery || showComms) && shareableUrl ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 px-0"
                    onClick={copyShareableUrl}
                    aria-label="Copy URL"
                  >
                    <IconCopy className="h-3.5 w-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Copy shareable delivery URL</TooltipContent>
              </Tooltip>
            ) : null}
            {showDelivery || showComms ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 px-0"
                    onClick={() => setDraftOpen(true)}
                    aria-label="Draft outbound"
                  >
                    <IconMail className="h-3.5 w-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Draft outbound access email</TooltipContent>
              </Tooltip>
            ) : null}
            <Tooltip>
              <TooltipTrigger asChild>
                <Link
                  to="/requests/$requestId"
                  params={{ requestId: item.request_id }}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ink hover:bg-canvas"
                  aria-label="Open full request page"
                >
                  <IconExternal className="h-3.5 w-3.5" />
                </Link>
              </TooltipTrigger>
              <TooltipContent>Open full request history</TooltipContent>
            </Tooltip>
            {copyNote ? (
              <span className="ml-1 text-[0.65rem] text-mute">{copyNote}</span>
            ) : null}
            {actionError ? (
              <span className="ml-1 text-[0.65rem] text-red-700">{actionError}</span>
            ) : null}
          </div>
        </div>

        {stages.length > 0 ? (
          <div className="shrink-0 border-b border-line px-4 py-2.5">
            <JourneyProgressBar stages={stages} />
          </div>
        ) : null}

        <Tabs defaultValue={primaryTab} className="flex min-h-0 flex-1 flex-col">
          <div className="shrink-0 border-b border-line px-4 pt-2">
            <TabsList className="h-7 w-full justify-start bg-transparent p-0">
              {showTriage ? (
                <TabsTrigger value="triage" className="h-6 px-2 text-[0.65rem]">
                  Triage
                </TabsTrigger>
              ) : null}
              {showResolveMatching ? (
                <TabsTrigger value="matching" className="h-6 px-2 text-[0.65rem]">
                  Matching
                </TabsTrigger>
              ) : null}
              {showHandoffTab ? (
                <TabsTrigger value="delivery" className="h-6 px-2 text-[0.65rem]">
                  {showDelivery ? 'Delivery' : 'Handoff'}
                </TabsTrigger>
              ) : null}
              {showNotice ? (
                <TabsTrigger value="notice" className="h-6 px-2 text-[0.65rem]">
                  Notice
                </TabsTrigger>
              ) : null}
              {showComms && showDelivery ? (
                <TabsTrigger value="comms" className="h-6 px-2 text-[0.65rem]">
                  Comms
                </TabsTrigger>
              ) : null}
              <TabsTrigger value="comments" className="h-6 gap-1 px-2 text-[0.65rem]">
                {showLegalEscalation ? 'Escalation' : 'Comments'}
                {comments.length > 0 ? (
                  <span className="tabular-nums opacity-70">({comments.length})</span>
                ) : null}
              </TabsTrigger>
            </TabsList>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {showTriage ? (
              <TabsContent value="triage" className="mt-0 space-y-2 text-xs">
                <p className="text-ink-soft">
                  Condition routed this request here before matching. Reject as DROP{' '}
                  <span className="font-mono">2</span> Exempted, or send to matching for the
                  data owner.
                </p>
                {item.requestor_state ? (
                  <p className="text-mute">
                    Requestor state:{' '}
                    <span className="font-medium text-ink">{item.requestor_state}</span>
                  </p>
                ) : null}
              </TabsContent>
            ) : null}

            {showResolveMatching ? (
              <TabsContent value="matching" className="mt-0">
                <MatchingReviewPanel
                  requestId={item.request_id}
                  matching={matchingQuery.data}
                  isPending={matchingQuery.isPending}
                  isError={matchingQuery.isError}
                  canReviewActions={canReviewActions}
                  actionPending={actionPending}
                  actionError={actionError}
                  onPromote={(responseStatus) =>
                    promoteMutation.mutate(responseStatus)
                  }
                  onDecline={() => declineMutation.mutate()}
                  compact
                  layout="tabs"
                  hideActions
                />
              </TabsContent>
            ) : null}

            {showHandoffTab ? (
              <TabsContent value="delivery" className="mt-0 space-y-3">
                <AccessHandoffPanel
                  requestId={item.request_id}
                  artifact={artifactQuery.data}
                  isPending={artifactQuery.isFetching && !artifactQuery.data}
                  isError={artifactQuery.isError}
                  canMutate={canReviewActions}
                  busy={deliveryMutation.isPending}
                  onCopyUrl={copyShareableUrl}
                  onSetStatus={(status) => deliveryMutation.mutate(status)}
                />
                {showComms && !showDelivery ? (
                  <p className="text-xs text-ink-soft">
                    Requester communications will thread here as outbound and inbound messages
                    are recorded.
                  </p>
                ) : null}
              </TabsContent>
            ) : null}

            {showNotice ? (
              <TabsContent value="notice" className="mt-0 space-y-2 text-xs">
                <p className="text-ink-soft">
                  DROP path after fulfill: approve{' '}
                  <span className="font-mono">notice.review</span>, then Wed upload — not a
                  consumer URL.
                </p>
                <p className="text-mute">Next upload window: Wed 00:00 America/Los_Angeles</p>
                {canReviewActions ? (
                  <Button
                    type="button"
                    size="sm"
                    className="mt-2"
                    disabled={actionPending}
                    onClick={() => setConfirmAction('notice_approve')}
                  >
                    Approve notice
                  </Button>
                ) : null}
              </TabsContent>
            ) : null}

            {showComms && showDelivery ? (
              <TabsContent value="comms" className="mt-0 text-xs text-ink-soft">
                <p className="font-medium text-ink">Requester communications</p>
                <p className="mt-1">
                  Outbound drafts, sent attempts, and inbound replies will thread here. Use
                  Draft outbound on Delivery items for access URL emails today.
                </p>
              </TabsContent>
            ) : null}

            <TabsContent value="comments" className="mt-0 space-y-2">
              <div className="max-h-64 space-y-1 overflow-y-auto">
                {commentsQuery.isError ? (
                  <p className="text-[0.7rem] text-red-700">Could not load comments.</p>
                ) : null}
                {!commentsQuery.isPending && !commentsQuery.isError && comments.length === 0 ? (
                  <p className="text-[0.7rem] text-mute">No comments yet.</p>
                ) : null}
                {comments.map((comment) => (
                  <div key={comment.id} className="border-b border-line/70 py-1.5 last:border-0">
                    <div className="flex flex-wrap items-baseline justify-between gap-1">
                      <span className="text-[0.65rem] font-medium text-ink">{comment.actor}</span>
                      <span className="tabular-nums text-[0.6rem] text-mute">
                        {formatRelativeTime(comment.occurred_at)}
                      </span>
                    </div>
                    <p className="whitespace-pre-wrap text-[0.7rem] text-ink-soft">
                      {comment.body}
                    </p>
                  </div>
                ))}
              </div>
              {canReviewActions ? (
                <div className="flex items-end gap-2 border-t border-line pt-2">
                  <textarea
                    className="min-h-[2.5rem] max-h-20 flex-1 resize-y rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
                    value={commentDraft}
                    onChange={(event) => setCommentDraft(event.target.value)}
                    placeholder="Add a review note…"
                    aria-label="Comment body"
                    maxLength={2000}
                  />
                  <Button
                    size="sm"
                    disabled={commentMutation.isPending || commentDraft.trim().length === 0}
                    onClick={() => commentMutation.mutate(commentDraft.trim())}
                  >
                    {commentMutation.isPending ? '…' : 'Post'}
                  </Button>
                </div>
              ) : null}
              {commentError ? (
                <p className="text-[0.65rem] text-red-700">{commentError}</p>
              ) : null}
            </TabsContent>
          </div>
        </Tabs>

        <Dialog open={draftOpen} onOpenChange={setDraftOpen}>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>Draft access delivery</DialogTitle>
              <DialogDescription>
                Template for external email — copy subject and body, then send outside the
                platform.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3 text-xs">
              <div>
                <p className="taste-micro">Subject</p>
                <p className="mt-1 rounded-md border border-line bg-paper px-2 py-1.5 text-ink">
                  {outboundDraft.subject}
                </p>
              </div>
              <div>
                <p className="taste-micro">Body</p>
                <pre className="mt-1 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border border-line bg-paper px-2 py-1.5 font-sans text-[0.75rem] text-ink">
                  {outboundDraft.body}
                </pre>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  type="button"
                  onClick={() => {
                    void navigator.clipboard.writeText(outboundDraft.body).then(() => {
                      setCopyNote('Copied draft body')
                      window.setTimeout(() => setCopyNote(null), 2000)
                    })
                  }}
                >
                  Copy body
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  type="button"
                  onClick={() => {
                    void navigator.clipboard.writeText(outboundDraft.subject).then(() => {
                      setCopyNote('Copied subject')
                      window.setTimeout(() => setCopyNote(null), 2000)
                    })
                  }}
                >
                  Copy subject
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </TooltipProvider>
  )
}



type InboxRow =
  | {
      kind: 'thread'
      batchKey: string
      batchLabel: string
      items: NeedsAttentionItem[]
    }
  | { kind: 'request'; item: NeedsAttentionItem }

type ActiveTarget =
  | { kind: 'thread'; batchKey: string }
  | { kind: 'request'; requestId: string }

/** Prefer download attempt id; fall back to ZIP member name (seed/broker rows). */
function inboxBatchKey(item: NeedsAttentionItem): string | null {
  if (item.match_type !== 'single_match') return null
  if (item.bulk_process_id != null) return `p:${item.bulk_process_id}`
  if (item.source_csv_filename) return `c:${item.source_csv_filename}`
  return null
}

function inboxBatchLabel(item: NeedsAttentionItem): string {
  if (item.bulk_process_id != null) return `#${item.bulk_process_id}`
  const name = item.source_csv_filename?.split('/').pop() ?? item.source_csv_filename
  if (!name) return 'batch'
  return name.replace(/\.csv$/i, '')
}

function compactMetaLine(item: NeedsAttentionItem): string {
  const parts = [
    SOURCE_LABELS[item.intake_source] ?? item.intake_source,
    item.current_stage.replaceAll('_', ' '),
    reasonLabel(item.reason),
  ]
  if (item.bulk_process_id != null || item.source_csv_filename) {
    parts.push(inboxBatchLabel(item))
  }
  return parts.join(' · ')
}

/** Threads only when browsing Matching (or All) with no result-type/due filter. */
function shouldGroupThreads(
  inboxKind: InboxKind,
  matchFilter: MatchFilter,
  dueFilter: DueFilter,
): boolean {
  return (
    (inboxKind === 'all' || inboxKind === 'matching') &&
    matchFilter === 'all' &&
    dueFilter === 'all'
  )
}

/** Exact 1:1 matches from the same DROP batch → one expandable thread (ungrouped when filters on). */
function buildInboxRows(
  items: NeedsAttentionItem[],
  groupThreads: boolean,
): InboxRow[] {
  if (!groupThreads) {
    return items.map((item) => ({ kind: 'request' as const, item }))
  }

  const byBatch = new Map<string, NeedsAttentionItem[]>()
  const individuals: NeedsAttentionItem[] = []

  for (const item of items) {
    const key = inboxBatchKey(item)
    if (key != null) {
      const list = byBatch.get(key) ?? []
      list.push(item)
      byBatch.set(key, list)
    } else {
      individuals.push(item)
    }
  }

  type Timed = { t: string; row: InboxRow }
  const timed: Timed[] = []

  for (const [batchKey, members] of byBatch) {
    const sorted = [...members].sort((a, b) =>
      (a.requested_at ?? '').localeCompare(b.requested_at ?? ''),
    )
    if (sorted.length >= 2) {
      timed.push({
        t: sorted[0]?.requested_at ?? '',
        row: {
          kind: 'thread',
          batchKey,
          batchLabel: inboxBatchLabel(sorted[0]!),
          items: sorted,
        },
      })
    } else {
      for (const item of sorted) {
        timed.push({
          t: item.requested_at ?? '',
          row: { kind: 'request', item },
        })
      }
    }
  }

  for (const item of individuals) {
    timed.push({
      t: item.requested_at ?? '',
      row: { kind: 'request', item },
    })
  }

  timed.sort((a, b) => a.t.localeCompare(b.t))
  return timed.map((entry) => entry.row)
}

function ThreadReviewPane({
  batchLabel,
  items,
  canReviewActions,
  onPromoteAll,
  onDeclineAll,
  actionPending,
  actionError,
  onBackToQueue,
}: {
  batchLabel: string
  items: NeedsAttentionItem[]
  canReviewActions: boolean
  onPromoteAll: (responseStatus: DropResponseStatusCode) => void
  onDeclineAll: () => void
  actionPending: boolean
  actionError: string | null
  onBackToQueue?: () => void
}) {
  const [confirm, setConfirm] = useState<'fulfill' | 'decline' | null>(null)
  // Exact 1:1 thread → Deleted (3) by default.
  const [fulfillStatus, setFulfillStatus] = useState<DropResponseStatusCode | null>(3)
  const wasActionPending = useRef(false)
  useEffect(() => {
    if (wasActionPending.current && !actionPending) setConfirm(null)
    wasActionPending.current = actionPending
  }, [actionPending])
  const earliest = items.reduce<NeedsAttentionItem | null>((best, item) => {
    if (!best) return item
    return (item.requested_at ?? '') < (best.requested_at ?? '') ? item : best
  }, null)
  const bucket = earliest ? dueBucket(earliest) : 'unknown'

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ConfirmActionDialog
        open={confirm === 'fulfill'}
        onOpenChange={(open) => {
          if (!open && !actionPending) setConfirm(null)
          if (open) setFulfillStatus(3)
        }}
        title={`Bulk fulfill ${items.length} exact matches?`}
        description={`Approve matching review for all single-match requests from batch ${batchLabel} and set the CA DROP status result.`}
        confirmLabel={`Fulfill ${items.length}`}
        confirming={actionPending && confirm === 'fulfill'}
        confirmDisabled={fulfillStatus == null}
        onConfirm={() => {
          if (fulfillStatus != null) onPromoteAll(fulfillStatus)
        }}
      >
        <DropResponseStatusPicker
          value={fulfillStatus}
          onChange={setFulfillStatus}
          disabled={actionPending}
          suggested={3}
        />
      </ConfirmActionDialog>
      <ConfirmActionDialog
        open={confirm === 'decline'}
        onOpenChange={(open) => {
          if (!open && !actionPending) setConfirm(null)
        }}
        title={`Bulk decline ${items.length} exact matches?`}
        description={`Decline all single-match requests from batch ${batchLabel} without fulfillment.`}
        confirmLabel={`Decline ${items.length}`}
        tone="destructive"
        confirming={actionPending && confirm === 'decline'}
        onConfirm={() => onDeclineAll()}
      />

      <div className="shrink-0 space-y-2 border-b border-line px-4 py-3">
        {onBackToQueue ? (
          <button
            type="button"
            onClick={onBackToQueue}
            className="mb-1 text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline md:hidden"
          >
            ← Queue
          </button>
        ) : null}
        <Micro>Batch thread</Micro>
        <h2 className="text-sm font-medium text-ink">
          Exact 1:1 matches · {items.length} requests
        </h2>
        <dl className="flex flex-wrap gap-x-4 gap-y-1 text-[0.7rem] text-ink-soft">
          <div>
            Batch <span className="font-mono text-ink">{batchLabel}</span>
          </div>
          <div>
            Match <span className="text-ink">single match</span>
          </div>
          {earliest ? (
            <div>
              Due{' '}
              <span
                className={cn(
                  bucket === 'overdue'
                    ? 'text-red-700'
                    : bucket === 'due_soon'
                      ? 'text-amber-800'
                      : 'text-ink',
                )}
              >
                {formatDueLabel(earliest)}
              </span>
            </div>
          ) : null}
        </dl>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        <p className="text-xs text-ink-soft">
          These requests each matched exactly one DWID in DROP batch{' '}
          <span className="font-mono">{batchLabel}</span>. Fulfill the whole thread at once,
          or expand the thread in the list to open a single request.
        </p>
        <ul className="max-h-56 divide-y divide-line overflow-y-auto rounded-lg border border-line">
          {items.map((entry) => (
            <li
              key={entry.request_id}
              className="flex items-center justify-between gap-2 px-3 py-2 text-[0.7rem]"
            >
              <span className="font-mono text-ink">{entry.request_id.slice(0, 8)}…</span>
              <span className="text-mute">
                {entry.requestor_state ?? '—'}
                {entry.matched_via ? ` · ${entry.matched_via}` : ''}
              </span>
            </li>
          ))}
        </ul>
        {canReviewActions ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={actionPending} onClick={() => setConfirm('fulfill')}>
              {actionPending && confirm === 'fulfill'
                ? `Fulfilling ${items.length}…`
                : `Bulk fulfill #${items.length}`}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={actionPending}
              onClick={() => setConfirm('decline')}
            >
              {actionPending && confirm === 'decline' ? 'Declining…' : 'Bulk decline'}
            </Button>
          </div>
        ) : null}
        {actionError ? (
          <p className="text-[0.65rem] text-red-700">{actionError}</p>
        ) : null}
      </div>
    </div>
  )
}


export function NeedsAttentionPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const search = useSearch({ from: '/requests/needs-attention' })
  const bulkFilter = search.bulk
  const { isAdmin, isLegal, role, me, isLoading: meLoading } = useMe()
  const legalPersona = Boolean(isLegal) || role === 'legal'
  const dataOwnerPersona = role === 'data_owner'
  const canReviewActions =
    Boolean(isAdmin) || legalPersona || dataOwnerPersona
  const inboxTabs = legalPersona
    ? LEGAL_INBOX_KIND_TABS
    : dataOwnerPersona
      ? DATA_OWNER_INBOX_KIND_TABS
      : OPS_INBOX_KIND_TABS
  const defaultKind: InboxKind = legalPersona
    ? 'triage'
    : dataOwnerPersona || bulkFilter != null
      ? 'matching'
      : 'all'
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [activeTarget, setActiveTarget] = useState<ActiveTarget | null>(null)
  const [expandedThreads, setExpandedThreads] = useState<Set<string>>(new Set())
  const [inboxKind, setInboxKind] = useState<InboxKind>(
    () => (search.kind as InboxKind | undefined) ?? defaultKind,
  )
  const [matchFilter, setMatchFilter] = useState<MatchFilter>('all')
  const [dueFilter, setDueFilter] = useState<DueFilter>('all')

  useEffect(() => {
    if (search.kind) {
      setInboxKind(search.kind as InboxKind)
      return
    }
    if (bulkFilter != null && !legalPersona) {
      setInboxKind('matching')
      return
    }
    if (legalPersona) setInboxKind('triage')
    else if (dataOwnerPersona) setInboxKind('matching')
  }, [bulkFilter, dataOwnerPersona, legalPersona, search.kind])

  const [bulkError, setBulkError] = useState<string | null>(null)
  const [bulkAssignee, setBulkAssignee] = useState('')
  const [threadActionError, setThreadActionError] = useState<string | null>(null)
  const [bulkConfirm, setBulkConfirm] = useState<
    | 'fulfill'
    | 'decline'
    | 'assign'
    | 'triage_reject'
    | 'triage_match'
    | 'notice_approve'
    | null
  >(null)
  /** Narrow viewports: queue or detail — never stack the pane under the list. */
  const [mobilePane, setMobilePane] = useState<'queue' | 'detail'>('queue')

  const attentionQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      'needs-attention',
      legalPersona ? 'legal' : 'ops',
    ],
    // Max allowed by admin-api — Select all must cover every filter match loaded,
    // not just the rows currently scrolled into the queue pane.
    queryFn: () =>
      legalPersona ? getLegalNeedsAttention(1000) : getNeedsAttention(1000),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  function setInboxKindAndUrl(next: InboxKind) {
    setInboxKind(next)
    setMobilePane('queue')
    if (next !== 'matching' && next !== 'all') {
      setMatchFilter('all')
    }
    void navigate({
      to: '/requests/needs-attention',
      search: {
        bulk: bulkFilter,
        kind: next === defaultKind && !legalPersona ? undefined : next,
      },
      replace: true,
    })
  }

  const items = attentionQuery.data?.items ?? []

  const assigneeCandidates = useMemo(() => {
    const set = new Set<string>()
    if (me?.email) set.add(me.email)
    for (const item of items) {
      const email = item.assignment?.assignee_identity?.trim()
      if (email) set.add(email)
    }
    return [...set].sort((a, b) => a.localeCompare(b))
  }, [items, me?.email])

  const kindCounts = useMemo(() => {
    const myEmail = me?.email
    let matching = 0
    let triage = 0
    let escalations = 0
    let delivery = 0
    let notice = 0
    let communications = 0
    let pendingTasks = 0
    for (const item of items) {
      if (isMatchingItem(item)) matching += 1
      if (isTriageItem(item)) triage += 1
      if (isEscalationItem(item)) escalations += 1
      if (isDeliveryItem(item)) delivery += 1
      if (isNoticeItem(item)) notice += 1
      if (isCommsItem(item)) communications += 1
      if (isPendingTaskFor(item, myEmail)) pendingTasks += 1
    }
    return {
      all: items.length,
      matching,
      triage,
      escalations,
      delivery,
      notice,
      communications,
      pending_tasks: pendingTasks,
    } satisfies Record<InboxKind, number>
  }, [items, me?.email])

  const matchOptions = useMemo(() => {
    const pool = items.filter(isMatchingItem)
    const counts = new Map<MatchFilter, number>()
    for (const item of pool) {
      const key = (item.match_type as MatchFilter | undefined) ?? 'unknown'
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    return (
      ['single_match', 'multi_match', 'not_found', 'unknown'] as MatchFilter[]
    )
      .filter((key) => (counts.get(key) ?? 0) > 0)
      .map((key) => [key, counts.get(key) ?? 0] as const)
  }, [items])

  const dueOptions = useMemo(() => {
    const counts = new Map<DueFilter, number>()
    for (const item of items) {
      const bucket = dueBucket(item)
      if (bucket === 'unknown') continue
      counts.set(bucket, (counts.get(bucket) ?? 0) + 1)
    }
    return (['overdue', 'due_soon', 'on_track'] as DueFilter[])
      .filter((key) => (counts.get(key) ?? 0) > 0)
      .map((key) => [key, counts.get(key) ?? 0] as const)
  }, [items])

  const filteredItems = useMemo(() => {
    const myEmail = me?.email
    return items.filter((item) => {
      if (bulkFilter != null && item.bulk_process_id !== bulkFilter) return false
      if (inboxKind === 'matching' && !isMatchingItem(item)) return false
      if (inboxKind === 'triage' && !isTriageItem(item)) return false
      if (inboxKind === 'escalations' && !isEscalationItem(item)) return false
      if (inboxKind === 'delivery' && !isDeliveryItem(item)) return false
      if (inboxKind === 'notice' && !isNoticeItem(item)) return false
      if (inboxKind === 'communications' && !isCommsItem(item)) return false
      if (inboxKind === 'pending_tasks' && !isPendingTaskFor(item, myEmail)) {
        return false
      }
      if (inboxKind === 'matching' || inboxKind === 'all') {
        if (matchFilter !== 'all') {
          const key = (item.match_type as MatchFilter | undefined) ?? 'unknown'
          if (key !== matchFilter) return false
        }
      }
      if (dueFilter !== 'all' && dueBucket(item) !== dueFilter) return false
      return true
    })
  }, [items, inboxKind, matchFilter, dueFilter, me?.email, bulkFilter])

  const groupThreads = shouldGroupThreads(inboxKind, matchFilter, dueFilter)

  const inboxRows = useMemo(
    () => buildInboxRows(filteredItems, groupThreads),
    [filteredItems, groupThreads],
  )

  useEffect(() => {
    if (inboxRows.length === 0) {
      setActiveTarget(null)
      return
    }
    const stillValid =
      activeTarget != null &&
      (activeTarget.kind === 'thread'
        ? inboxRows.some(
          (row) =>
            row.kind === 'thread' && row.batchKey === activeTarget.batchKey,
        )
        : filteredItems.some((item) => item.request_id === activeTarget.requestId))
    if (!stillValid) {
      const first = inboxRows[0]!
      setActiveTarget(
        first.kind === 'thread'
          ? { kind: 'thread', batchKey: first.batchKey }
          : { kind: 'request', requestId: first.item.request_id },
      )
    }
  }, [inboxRows, filteredItems, activeTarget])

  const activeThread =
    activeTarget?.kind === 'thread'
      ? (inboxRows.find(
        (row): row is Extract<InboxRow, { kind: 'thread' }> =>
          row.kind === 'thread' && row.batchKey === activeTarget.batchKey,
      ) ?? null)
      : null

  const activeItem =
    activeTarget?.kind === 'request'
      ? (filteredItems.find((item) => item.request_id === activeTarget.requestId) ??
        null)
      : null

  const filteredIds = useMemo(
    () => filteredItems.map((item) => item.request_id),
    [filteredItems],
  )

  const allFilteredSelected =
    filteredIds.length > 0 && filteredIds.every((id) => selectedIds.has(id))
  const someFilteredSelected = filteredIds.some((id) => selectedIds.has(id))

  const [bulkFulfillStatus, setBulkFulfillStatus] =
    useState<DropResponseStatusCode | null>(3)

  const bulkMutation = useMutation({
    mutationFn: async ({
      action,
      requestIds,
      responseStatus,
    }: {
      action: 'fulfill' | 'decline'
      requestIds: string[]
      responseStatus?: DropResponseStatusCode
    }) => {
      const results = await Promise.allSettled(
        requestIds.map((requestId) =>
          action === 'fulfill'
            ? postDropMatchingResultPromote(requestId, {
                response_status: responseStatus,
              })
            : postDropMatchingResultDecline(requestId),
        ),
      )
      const failedResults = results.filter(
        (result): result is PromiseRejectedResult => result.status === 'rejected',
      )
      const failed = failedResults.length
      const succeeded = results.length - failed
      const sample =
        failedResults[0]?.reason instanceof Error
          ? failedResults[0].reason.message
          : failedResults[0]
            ? String(failedResults[0].reason)
            : null
      return { succeeded, failed, action, sample }
    },
    onSuccess: async (result) => {
      const verb = result.action === 'fulfill' ? 'fulfilled' : 'declined'
      const message =
        result.failed > 0
          ? `${result.succeeded} ${verb}, ${result.failed} failed${
              result.sample ? ` — ${result.sample}` : ''
            }`
          : null
      setBulkError(message)
      setThreadActionError(message)
      setSelectedIds(new Set())
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : 'Bulk action failed'
      setBulkError(message)
      setThreadActionError(message)
      setBulkConfirm(null)
    },
  })

  const bulkAssignMutation = useMutation({
    mutationFn: async ({
      requestIds,
      assignee,
    }: {
      requestIds: string[]
      assignee: string
    }) =>
      postDropWorkflowAssign({
        request_ids: requestIds,
        assignee_identity: assignee,
        target_role: 'reviewer',
      }),
    onSuccess: async () => {
      setBulkError(null)
      setBulkAssignee('')
      setSelectedIds(new Set())
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setBulkError(error instanceof Error ? error.message : 'Bulk assign failed')
      setBulkConfirm(null)
    },
  })

  const bulkTriageRejectMutation = useMutation({
    mutationFn: (requestIds: string[]) =>
      postTriageBulkReject({ request_ids: requestIds, response_status: 2 }),
    onSuccess: async (result) => {
      setBulkError(
        result.count === 0 ? 'No triage rows rejected' : null,
      )
      setSelectedIds(new Set())
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setBulkError(error instanceof Error ? error.message : 'Bulk reject failed')
      setBulkConfirm(null)
    },
  })

  const bulkTriageMatchMutation = useMutation({
    mutationFn: (requestIds: string[]) =>
      postTriageSendToMatching({ request_ids: requestIds }),
    onSuccess: async () => {
      setBulkError(null)
      setSelectedIds(new Set())
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setBulkError(
        error instanceof Error ? error.message : 'Send to matching failed',
      )
      setBulkConfirm(null)
    },
  })

  const bulkNoticeApproveMutation = useMutation({
    mutationFn: (requestIds: string[]) =>
      postNoticeApprove({ request_ids: requestIds }),
    onSuccess: async (result) => {
      setBulkError(
        result.count === 0 ? 'No notice rows approved' : null,
      )
      setSelectedIds(new Set())
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setBulkError(
        error instanceof Error ? error.message : 'Notice approve failed',
      )
      setBulkConfirm(null)
    },
  })

  const loading = attentionQuery.isPending && !attentionQuery.data
  const triageBulkPending =
    bulkTriageRejectMutation.isPending || bulkTriageMatchMutation.isPending
  const noticeBulkPending = bulkNoticeApproveMutation.isPending

  function toggleId(requestId: string) {
    setSelectedIds((previous) => {
      const next = new Set(previous)
      if (next.has(requestId)) next.delete(requestId)
      else next.add(requestId)
      return next
    })
  }

  function toggleSelectAll() {
    setSelectedIds((previous) => {
      if (allFilteredSelected) {
        const next = new Set(previous)
        for (const id of filteredIds) next.delete(id)
        return next
      }
      const next = new Set(previous)
      for (const id of filteredIds) next.add(id)
      return next
    })
  }

  function toggleThreadExpand(batchKey: string) {
    setExpandedThreads((previous) => {
      const next = new Set(previous)
      if (next.has(batchKey)) next.delete(batchKey)
      else next.add(batchKey)
      return next
    })
  }

  function toggleThreadSelect(requestIds: string[]) {
    setSelectedIds((previous) => {
      const allSelected = requestIds.every((id) => previous.has(id))
      const next = new Set(previous)
      if (allSelected) {
        for (const id of requestIds) next.delete(id)
      } else {
        for (const id of requestIds) next.add(id)
      }
      return next
    })
  }

  function runBulk(action: 'fulfill' | 'decline', responseStatus?: DropResponseStatusCode) {
    // Always act on the full filtered set when select-all is checked — not only
    // what happens to be scrolled into the left pane viewport.
    const requestIds = allFilteredSelected ? [...filteredIds] : [...selectedIds]
    if (requestIds.length === 0) return
    bulkMutation.mutate({ action, requestIds, responseStatus })
  }

  const selectedCount = selectedIds.size
  const selectedInFilterCount = filteredIds.filter((id) => selectedIds.has(id)).length

  if (meLoading) {
    return (
      <section className="space-y-4 py-6">
        <SkeletonLines lines={6} />
      </section>
    )
  }

  return (
    <section className="flex h-[calc(100vh-6.5rem)] flex-col gap-3">
      <ConfirmActionDialog
        open={bulkConfirm === 'fulfill'}
        onOpenChange={(open) => {
          if (!open && !bulkMutation.isPending) setBulkConfirm(null)
          if (open) setBulkFulfillStatus(3)
        }}
        title={`Fulfill ${allFilteredSelected ? filteredIds.length : selectedCount} request${
          (allFilteredSelected ? filteredIds.length : selectedCount) === 1 ? '' : 's'
        }?`}
        description="Selected items leave matching review with the CA DROP status result you confirm below."
        confirmLabel="Fulfill selected"
        confirming={bulkMutation.isPending && bulkConfirm === 'fulfill'}
        confirmDisabled={bulkFulfillStatus == null}
        onConfirm={() => {
          if (bulkFulfillStatus != null) runBulk('fulfill', bulkFulfillStatus)
        }}
      >
        <DropResponseStatusPicker
          value={bulkFulfillStatus}
          onChange={setBulkFulfillStatus}
          disabled={bulkMutation.isPending}
          suggested={3}
        />
      </ConfirmActionDialog>
      <ConfirmActionDialog
        open={bulkConfirm === 'decline'}
        onOpenChange={(open) => {
          if (!open && !bulkMutation.isPending) setBulkConfirm(null)
        }}
        title={`Decline ${allFilteredSelected ? filteredIds.length : selectedCount} request${
          (allFilteredSelected ? filteredIds.length : selectedCount) === 1 ? '' : 's'
        }?`}
        description="Selected items will leave the review queue without fulfillment."
        confirmLabel="Decline selected"
        tone="destructive"
        confirming={bulkMutation.isPending && bulkConfirm === 'decline'}
        onConfirm={() => runBulk('decline')}
      />
      <ConfirmActionDialog
        open={bulkConfirm === 'assign'}
        onOpenChange={(open) => {
          if (!open && !bulkAssignMutation.isPending) setBulkConfirm(null)
        }}
        title={`Assign ${selectedCount} request${selectedCount === 1 ? '' : 's'}?`}
        description={`Assign selected reviews to ${bulkAssignee.trim() || 'the reviewer'}.`}
        confirmLabel="Assign selected"
        confirming={bulkAssignMutation.isPending}
        onConfirm={() => {
          bulkAssignMutation.mutate({
            requestIds: allFilteredSelected ? [...filteredIds] : [...selectedIds],
            assignee: bulkAssignee.trim(),
          })
        }}
      />
      <ConfirmActionDialog
        open={bulkConfirm === 'triage_reject'}
        onOpenChange={(open) => {
          if (!open && !bulkTriageRejectMutation.isPending) setBulkConfirm(null)
        }}
        title={`Reject ${allFilteredSelected ? filteredIds.length : selectedCount} as Exempted?`}
        description="Sets CA DROP response_status = 2 (Exempted) and closes Legal Triage for the selected requests."
        confirmLabel="Reject as Exempted"
        tone="destructive"
        confirming={bulkTriageRejectMutation.isPending}
        onConfirm={() => {
          const requestIds = allFilteredSelected ? [...filteredIds] : [...selectedIds]
          if (requestIds.length > 0) bulkTriageRejectMutation.mutate(requestIds)
        }}
      />
      <ConfirmActionDialog
        open={bulkConfirm === 'triage_match'}
        onOpenChange={(open) => {
          if (!open && !bulkTriageMatchMutation.isPending) setBulkConfirm(null)
        }}
        title={`Send ${allFilteredSelected ? filteredIds.length : selectedCount} to matching?`}
        description="Releases Triage holds and enqueues auto-match for the data-owner queue."
        confirmLabel="Send to matching"
        confirming={bulkTriageMatchMutation.isPending}
        onConfirm={() => {
          const requestIds = allFilteredSelected ? [...filteredIds] : [...selectedIds]
          if (requestIds.length > 0) bulkTriageMatchMutation.mutate(requestIds)
        }}
      />
      <ConfirmActionDialog
        open={bulkConfirm === 'notice_approve'}
        onOpenChange={(open) => {
          if (!open && !bulkNoticeApproveMutation.isPending) setBulkConfirm(null)
        }}
        title={`Approve notice for ${allFilteredSelected ? filteredIds.length : selectedCount}?`}
        description="Clears notice.review so selected DROP rows can enter the Wednesday upload batch."
        confirmLabel="Approve notice"
        confirming={bulkNoticeApproveMutation.isPending}
        onConfirm={() => {
          const requestIds = allFilteredSelected ? [...filteredIds] : [...selectedIds]
          if (requestIds.length > 0) bulkNoticeApproveMutation.mutate(requestIds)
        }}
      />
      <header className="flex shrink-0 flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>
            {legalPersona ? 'Legal' : dataOwnerPersona ? 'Data owner' : 'Requests'}
          </Micro>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              Inbox
            </h2>
            {attentionQuery.isFetching && !attentionQuery.isPending ? (
              <span className="taste-frost-chip text-[0.65rem]">Refreshing</span>
            ) : null}
            {bulkMutation.isPending ||
            bulkAssignMutation.isPending ||
            triageBulkPending ||
            noticeBulkPending ? (
              <span className="taste-frost-chip text-[0.65rem]" role="status" aria-live="polite">
                {bulkNoticeApproveMutation.isPending
                  ? 'Approving notice…'
                  : bulkTriageRejectMutation.isPending
                    ? 'Rejecting…'
                    : bulkTriageMatchMutation.isPending
                      ? 'Sending…'
                      : bulkMutation.isPending
                        ? bulkConfirm === 'decline'
                          ? 'Declining…'
                          : 'Fulfilling…'
                        : 'Assigning…'}
              </span>
            ) : null}
            {attentionQuery.data && attentionQuery.data.items.length > 0 ? (
              <Badge variant="notification" aria-label={`${attentionQuery.data.items.length} to review`}>
                {attentionQuery.data.items.length > 99
                  ? '99+'
                  : attentionQuery.data.items.length}
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 max-w-lg text-xs text-ink-soft">
            {legalPersona
              ? 'Case queue — Triage condition holds, Escalations from data owners, then Notice and Delivery after fulfill. Matching review stays on data-owner My work.'
              : dataOwnerPersona
                ? 'Approve recommended CA DROP status on Matching, or open Tasks assigned to you. Escalate to Legal when you need a hold.'
                : 'Pending work stays in Inbox lanes — matching, delivery (shareable URL), DROP notice, and requester comms. Exact 1:1 matches in one DROP batch group as a thread for bulk fulfill.'}
          </p>
          {bulkFilter != null ? (
            <p className="mt-1.5 flex flex-wrap items-center gap-2 text-[0.7rem]">
              <span className="taste-frost-chip tabular-nums">
                Bulk run #{bulkFilter}
              </span>
              <button
                type="button"
                className="font-medium text-habeas-navy underline-offset-2 hover:underline"
                onClick={() =>
                  void navigate({
                    to: '/requests/needs-attention',
                    search: {},
                  })
                }
              >
                Clear bulk filter
              </button>
            </p>
          ) : null}
        </div>
        <Link to="/requests" className="taste-btn text-xs">
          All requests
        </Link>
      </header>

      <div className="taste-panel grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]">
        <div
          className={cn(
            'min-h-0 flex-col border-line md:border-r',
            mobilePane === 'detail' ? 'hidden md:flex' : 'flex',
          )}
        >
          <div className="space-y-1.5 border-b border-line px-2.5 py-2">
            <Tabs
              value={inboxKind}
              onValueChange={(value) => setInboxKindAndUrl(value as InboxKind)}
            >
              <TabsList className="h-7 w-full justify-start gap-0.5 overflow-x-auto bg-canvas p-0.5">
                {inboxTabs.map((tab) => (
                  <TabsTrigger
                    key={tab.value}
                    value={tab.value}
                    className="h-6 gap-1 px-1.5 text-[0.65rem]"
                  >
                    {tab.label}
                    <span className="tabular-nums opacity-70">{kindCounts[tab.value]}</span>
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>

            {!legalPersona &&
            (inboxKind === 'matching' || inboxKind === 'all') &&
              (matchOptions.length > 0 || dueOptions.length > 0) ? (
              <div className="flex flex-wrap items-center gap-1">
                {inboxKind === 'matching' ? (
                  <>
                    <span className="mr-0.5 text-[0.6rem] uppercase tracking-wide text-mute">
                      Result
                    </span>
                    <FilterChip
                      active={matchFilter === 'all'}
                      label="All results"
                      onClick={() => setMatchFilter('all')}
                    />
                    {matchOptions.map(([matchType, count]) => (
                      <FilterChip
                        key={matchType}
                        active={matchFilter === matchType}
                        label={matchTypeLabel(matchType)}
                        count={count}
                        onClick={() =>
                          setMatchFilter((current) =>
                            current === matchType ? 'all' : matchType,
                          )
                        }
                      />
                    ))}
                  </>
                ) : null}
                {dueOptions.length > 0 ? (
                  <>
                    <span className="ml-1 mr-0.5 text-[0.6rem] uppercase tracking-wide text-mute">
                      Due
                    </span>
                    {dueOptions.map(([due, count]) => (
                      <FilterChip
                        key={due}
                        active={dueFilter === due}
                        label={
                          due === 'overdue'
                            ? 'Overdue'
                            : due === 'due_soon'
                              ? 'Due soon'
                              : 'On track'
                        }
                        count={count}
                        onClick={() =>
                          setDueFilter((current) => (current === due ? 'all' : due))
                        }
                      />
                    ))}
                  </>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
            <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-ink-soft">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 rounded border-line accent-habeas-navy"
                checked={allFilteredSelected}
                ref={(element) => {
                  if (element) {
                    element.indeterminate = someFilteredSelected && !allFilteredSelected
                  }
                }}
                onChange={toggleSelectAll}
                disabled={filteredIds.length === 0}
                aria-label="Select all matching current filters"
              />
              Select all
            </label>

            {isAdmin && !legalPersona ? (
              <>
                <Button
                  size="sm"
                  disabled={selectedCount === 0 || bulkMutation.isPending}
                  onClick={() => setBulkConfirm('fulfill')}
                >
                  {bulkMutation.isPending && bulkConfirm === 'fulfill'
                    ? 'Fulfilling…'
                    : 'Fulfill'}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={selectedCount === 0 || bulkMutation.isPending}
                  onClick={() => setBulkConfirm('decline')}
                >
                  {bulkMutation.isPending && bulkConfirm === 'decline'
                    ? 'Declining…'
                    : 'Decline'}
                </Button>
              </>
            ) : null}

            {legalPersona && inboxKind === 'triage' ? (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={selectedCount === 0 || triageBulkPending}
                  onClick={() => setBulkConfirm('triage_reject')}
                >
                  {bulkTriageRejectMutation.isPending ? 'Rejecting…' : 'Reject 2'}
                </Button>
                <Button
                  size="sm"
                  disabled={selectedCount === 0 || triageBulkPending}
                  onClick={() => setBulkConfirm('triage_match')}
                >
                  {bulkTriageMatchMutation.isPending ? 'Sending…' : 'Send to matching'}
                </Button>
              </>
            ) : null}

            {legalPersona && inboxKind === 'notice' ? (
              <Button
                size="sm"
                disabled={selectedCount === 0 || noticeBulkPending}
                onClick={() => setBulkConfirm('notice_approve')}
              >
                {bulkNoticeApproveMutation.isPending
                  ? 'Approving…'
                  : 'Approve notice'}
              </Button>
            ) : null}

            <div className="ml-auto flex items-center gap-2">
              {selectedCount > 0 ? (
                <span className="taste-frost-chip tabular-nums text-[0.65rem]">
                  {allFilteredSelected
                    ? `All ${filteredIds.length} in filter`
                    : `${selectedInFilterCount} of ${filteredIds.length} in filter`}
                  <button
                    type="button"
                    className="ml-1.5 text-mute hover:text-ink"
                    onClick={() => setSelectedIds(new Set())}
                    aria-label="Clear selection"
                  >
                    ×
                  </button>
                </span>
              ) : (
                <span className="text-[0.65rem] text-mute tabular-nums">
                  #{filteredItems.length} in filter
                  {items.length >= 1000 ? ' (capped at 1000)' : ''}
                  {groupThreads
                    ? ` · ${inboxRows.filter((row) => row.kind === 'thread').length} threads`
                    : ''}
                </span>
              )}
            </div>
          </div>

          {isAdmin && !legalPersona && selectedCount > 0 ? (
            <div className="flex flex-wrap items-end gap-2 border-b border-line px-3 py-2">
              <label className="flex min-w-[10rem] flex-1 flex-col gap-1 text-[0.65rem] text-ink-soft">
                Assign selected
                <input
                  className="rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
                  value={bulkAssignee}
                  onChange={(event) => setBulkAssignee(event.target.value)}
                  placeholder="reviewer@habeas.com"
                  aria-label="Bulk assignee email"
                />
              </label>
              <Button
                size="sm"
                variant="outline"
                disabled={
                  bulkAssignMutation.isPending || bulkAssignee.trim().length === 0
                }
                onClick={() => setBulkConfirm('assign')}
              >
                {bulkAssignMutation.isPending ? 'Assigning…' : 'Assign'}
              </Button>
            </div>
          ) : null}

          {bulkError ? (
            <p className="border-b border-line px-3 py-2 text-[0.7rem] text-red-700">
              {bulkError}
            </p>
          ) : null}

          <div className="min-h-0 flex-1 overflow-y-auto">
            {loading ? (
              <div className="p-4">
                <SkeletonLines lines={6} />
              </div>
            ) : null}
            {attentionQuery.isError ? (
              <p className="p-4 text-xs text-red-700">Could not load inbox.</p>
            ) : null}
            {!loading && !attentionQuery.isError && filteredItems.length === 0 ? (
              <p className="p-6 text-xs text-ink-soft">
                {items.length === 0
                  ? legalPersona
                    ? inboxKind === 'notice'
                      ? 'No DROP notice.review items — fulfilled rows with pending notice land here.'
                      : inboxKind === 'delivery'
                        ? 'No access delivery handoffs yet — rows appear after access packs get a delivery status.'
                        : inboxKind === 'triage'
                          ? 'No Legal Triage holds — condition hits land here before matching.'
                          : inboxKind === 'escalations'
                            ? 'No escalations from data owners right now.'
                            : inboxKind === 'pending_tasks'
                              ? 'No pending tasks assigned to you.'
                              : 'Nothing in the Legal case queue right now.'
                    : 'Nothing needs attention right now.'
                  : inboxKind === 'triage'
                    ? 'No Legal Triage holds — condition hits land here before matching.'
                    : inboxKind === 'escalations'
                      ? 'No escalations to Legal right now.'
                      : inboxKind === 'delivery'
                        ? 'No access delivery tasks in this filter.'
                        : inboxKind === 'notice'
                          ? 'No DROP notice.review items waiting.'
                          : inboxKind === 'communications'
                            ? 'No requester comms yet — drafts and replies will land here.'
                            : inboxKind === 'pending_tasks'
                              ? 'No pending tasks assigned to you.'
                              : 'No items match the current view.'}
              </p>
            ) : null}

            {!loading && !attentionQuery.isError && filteredItems.length > 0 ? (
              <ul className="divide-y divide-line">
                {inboxRows.map((row) => {
                  if (row.kind === 'thread') {
                    const ids = row.items.map((item) => item.request_id)
                    const selected = ids.every((id) => selectedIds.has(id))
                    const partial =
                      !selected && ids.some((id) => selectedIds.has(id))
                    const active =
                      activeTarget?.kind === 'thread' &&
                      activeTarget.batchKey === row.batchKey
                    const expanded = expandedThreads.has(row.batchKey)
                    const earliest = row.items[0]!
                    const bucket = dueBucket(earliest)
                    return (
                      <li key={`thread-${row.batchKey}`}>
                        <div
                          className={cn(
                            'relative flex items-stretch gap-0 border-l-2 border-l-habeas-navy/70 transition-colors',
                            active
                              ? 'bg-habeas-navy/[0.07]'
                              : selected
                                ? 'bg-habeas-navy/[0.03]'
                                : 'hover:bg-panel/50',
                          )}
                        >
                          <label
                            className="flex shrink-0 cursor-pointer items-center px-3"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <input
                              type="checkbox"
                              className="h-3.5 w-3.5 rounded border-line accent-habeas-navy"
                              checked={selected}
                              ref={(element) => {
                                if (element) element.indeterminate = partial
                              }}
                              onChange={() => toggleThreadSelect(ids)}
                              aria-label={`Select bulk batch ${row.batchLabel}`}
                            />
                          </label>
                          <button
                            type="button"
                            className="mt-0.5 shrink-0 self-start rounded px-1 py-2 text-[0.65rem] text-mute hover:bg-panel hover:text-ink"
                            aria-label={
                              expanded
                                ? `Collapse bulk batch ${row.batchLabel}`
                                : `Expand bulk batch ${row.batchLabel}`
                            }
                            onClick={() => toggleThreadExpand(row.batchKey)}
                          >
                            {expanded ? '▾' : '▸'}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setActiveTarget({
                                kind: 'thread',
                                batchKey: row.batchKey,
                              })
                              setMobilePane('detail')
                            }}
                            className="flex min-w-0 flex-1 items-start gap-2 px-1 py-2 pr-2 text-left"
                            aria-label={`Bulk inbox group batch ${row.batchLabel}, ${row.items.length} requests`}
                          >
                            <span
                              className="relative mt-0.5 flex h-6 w-7 shrink-0 items-center justify-center"
                              aria-hidden
                              title="Grouped bulk inbox item"
                            >
                              <span className="absolute left-0 top-0.5 h-5 w-5 rounded-md border border-habeas-navy/25 bg-habeas-navy/5" />
                              <span className="absolute left-1 top-0 h-5 w-5 rounded-md border border-habeas-navy/40 bg-habeas-navy/10" />
                              <span className="relative flex h-5 w-5 items-center justify-center rounded-md border border-habeas-navy/50 bg-paper text-[0.55rem] font-semibold tabular-nums text-habeas-navy">
                                {row.items.length > 99 ? '99+' : row.items.length}
                              </span>
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                                <span className="font-mono text-[0.7rem] font-medium text-ink">
                                  {row.batchLabel}
                                </span>
                                <Badge
                                  variant="run"
                                  className="normal-case tracking-normal"
                                >
                                  Bulk group
                                </Badge>
                                <span className="text-[0.7rem] text-mute">
                                  Exact 1:1 · {row.items.length} requests
                                </span>
                              </div>
                              <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                                <Badge
                                  variant="ok"
                                  className="normal-case tracking-normal"
                                >
                                  single match
                                </Badge>
                                <span
                                  className={cn(
                                    'text-[0.6rem] tabular-nums',
                                    bucket === 'overdue'
                                      ? 'text-red-700'
                                      : bucket === 'due_soon'
                                        ? 'text-amber-800'
                                        : 'text-mute',
                                  )}
                                >
                                  {formatDueLabel(earliest)}
                                </span>
                              </div>
                            </div>
                          </button>
                        </div>
                        {expanded ? (
                          <ul className="border-t border-line/70 bg-canvas/40">
                            {row.items.map((item) => {
                              const childSelected = selectedIds.has(item.request_id)
                              const childActive =
                                activeTarget?.kind === 'request' &&
                                activeTarget.requestId === item.request_id
                              return (
                                <li key={item.request_id}>
                                  <div
                                    className={cn(
                                      'flex items-stretch gap-0 pl-6 transition-colors',
                                      childActive
                                        ? 'bg-habeas-navy/[0.07]'
                                        : childSelected
                                          ? 'bg-habeas-navy/[0.03]'
                                          : 'hover:bg-panel/40',
                                    )}
                                  >
                                    <label
                                      className="flex shrink-0 cursor-pointer items-center px-3"
                                      onClick={(event) => event.stopPropagation()}
                                    >
                                      <input
                                        type="checkbox"
                                        className="h-3.5 w-3.5 rounded border-line accent-habeas-navy"
                                        checked={childSelected}
                                        onChange={() => toggleId(item.request_id)}
                                        aria-label={`Select ${item.request_id}`}
                                      />
                                    </label>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setActiveTarget({
                                          kind: 'request',
                                          requestId: item.request_id,
                                        })
                                        setMobilePane('detail')
                                      }}
                                      className="flex min-w-0 flex-1 items-center gap-2 px-1 py-1.5 pr-3 text-left"
                                    >
                                      <span className="font-mono text-[0.65rem] text-ink">
                                        {item.request_id.slice(0, 8)}…
                                      </span>
                                      <span className="text-[0.6rem] text-mute">
                                        {item.requestor_state ?? '—'}
                                      </span>
                                      {item.bulk_process_id != null ||
                                      item.source_csv_filename ? (
                                        <span className="ml-auto font-mono text-[0.6rem] text-mute">
                                          {inboxBatchLabel(item)}
                                        </span>
                                      ) : null}
                                    </button>
                                  </div>
                                </li>
                              )
                            })}
                          </ul>
                        ) : null}
                      </li>
                    )
                  }

                  const item = row.item
                  const selected = selectedIds.has(item.request_id)
                  const active =
                    activeTarget?.kind === 'request' &&
                    activeTarget.requestId === item.request_id
                  const bucket = dueBucket(item)
                  const assignee = item.assignment?.assignee_identity
                  return (
                    <li key={item.request_id}>
                      <div
                        className={cn(
                          'flex items-stretch gap-0 transition-colors',
                          active
                            ? 'bg-habeas-navy/[0.07]'
                            : selected
                              ? 'bg-habeas-navy/[0.03]'
                              : 'hover:bg-panel/50',
                        )}
                      >
                        <label
                          className="flex shrink-0 cursor-pointer items-center px-3"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <input
                            type="checkbox"
                            className="h-3.5 w-3.5 rounded border-line accent-habeas-navy"
                            checked={selected}
                            onChange={() => toggleId(item.request_id)}
                            aria-label={`Select ${item.request_id}`}
                          />
                        </label>
                        <button
                          type="button"
                          onClick={() => {
                            setActiveTarget({
                              kind: 'request',
                              requestId: item.request_id,
                            })
                            setMobilePane('detail')
                          }}
                          className="flex min-w-0 flex-1 flex-col gap-1 px-1 py-3 pr-3 text-left text-xs"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="min-w-0 truncate font-medium text-ink">
                              {inboxItemTitle(item)}
                            </span>
                            <span className="shrink-0 tabular-nums text-mute">
                              {formatRelativeTime(item.requested_at ?? item.received_at)}
                            </span>
                          </div>
                          <div className="flex flex-wrap items-center gap-1.5 text-[0.65rem] text-ink-soft">
                            <Avatar className="h-4 w-4">
                              <AvatarFallback className="text-[0.45rem]">
                                {emailInitials(assignee)}
                              </AvatarFallback>
                            </Avatar>
                            <span>
                              {SOURCE_LABELS[item.intake_source] ?? item.intake_source}
                            </span>
                            <span className="text-mute">·</span>
                            <span className="capitalize">
                              {isDeliveryItem(item)
                                ? 'delivery'
                                : isNoticeItem(item)
                                  ? 'notice'
                                  : isCommsItem(item)
                                    ? 'comms'
                                    : isMatchingItem(item)
                                      ? 'matching'
                                      : isPendingTaskFor(item, me?.email)
                                        ? 'task'
                                        : 'inbox'}
                            </span>
                            <span className="text-mute">·</span>
                            <span className="truncate font-mono text-mute">
                              {item.request_id.slice(0, 8)}…
                            </span>
                            {item.bulk_process_id != null ||
                            item.source_csv_filename ? (
                              <>
                                <span className="text-mute">·</span>
                                <span className="font-mono text-mute">
                                  {inboxBatchLabel(item)}
                                </span>
                              </>
                            ) : null}
                          </div>
                          <p
                            className={cn(
                              'text-[0.65rem]',
                              bucket === 'overdue'
                                ? 'text-red-700'
                                : bucket === 'due_soon'
                                  ? 'text-amber-800'
                                  : 'text-mute',
                            )}
                          >
                            {reasonLabel(item.reason)} · {formatDueLabel(item)}
                          </p>
                        </button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            ) : null}
          </div>
        </div>

        <div
          className={cn(
            'min-h-0 min-w-0 overflow-hidden',
            mobilePane === 'queue' ? 'hidden md:block' : 'block',
          )}
        >
          {activeThread ? (
            <ThreadReviewPane
              batchLabel={activeThread.batchLabel}
              items={activeThread.items}
              canReviewActions={canReviewActions}
              actionPending={bulkMutation.isPending}
              actionError={threadActionError}
              onBackToQueue={() => setMobilePane('queue')}
              onPromoteAll={(responseStatus) => {
                setThreadActionError(null)
                bulkMutation.mutate({
                  action: 'fulfill',
                  requestIds: activeThread.items.map((item) => item.request_id),
                  responseStatus,
                })
              }}
              onDeclineAll={() => {
                setThreadActionError(null)
                bulkMutation.mutate({
                  action: 'decline',
                  requestIds: activeThread.items.map((item) => item.request_id),
                })
              }}
            />
          ) : activeItem ? (
            <InboxReviewPane
              item={activeItem}
              canReviewActions={canReviewActions}
              assigneeCandidates={assigneeCandidates}
              legalPersona={legalPersona}
              onBackToQueue={() => setMobilePane('queue')}
            />
          ) : (
            <div className="flex h-full items-center justify-center p-8 text-xs text-ink-soft">
              {loading ? 'Loading review queue…' : 'Select a request to review.'}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
