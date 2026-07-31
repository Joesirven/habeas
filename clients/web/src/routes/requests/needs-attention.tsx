import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import type { LegalInboxFilter } from '@/router'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  AccessDeliveryEmailCard,
  useIsAccessRequest,
} from '@/components/fulfillment/AccessDeliveryEmail'
import {
  AccessHandoffPanel,
  DropResponseStatusPicker,
  MatchingReviewPanel,
} from '@/components/requests/RequestTriageDialog'
import {
  RequestDetailOverlay,
  FulfillmentGateControls,
  RequesterContactSection,
  ThinJourneyPipeline,
  useRequestDetailOverlay,
} from '@/components/requests/RequestDetailOverlay'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  ConfirmActionDialog,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { isLegalAdminPersona, useMe } from '@/lib/auth'
import {
  dropResponseStatusLabel,
  getDropMatchingResultDetail,
  getFulfillmentArtifact,
  getLatestIdentityVerification,
  getLegalNeedsAttention,
  getLegalOperators,
  getNeedsAttention,
  getBatchJourneyWorkbench,
  getRequest,
  getRequestComments,
  getRequestJourney,
  getRequestJourneyWorkbench,
  getRequestTimeline,
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
  type IdentityVerificationRecord,
  type IntakeSource,
  type MatchingResultDetail,
  type NeedsAttentionItem,
  type RequestRecord,
  type TimelineEntry,
  type WorkbenchVerticalBatchRow,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import {
  actionReasonLabel,
  deriveWorkbenchChromeFromOpsJourney,
  NOTICE_APPROVAL,
} from '@/lib/legalJourneyLabels'
import { cn, paginate } from '@/lib/utils'

/** Left-pane queue page size — keeps the dense inbox list scannable without one giant scroll. */
const INBOX_PAGE_SIZE = 30

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

const CHANNEL_ORIGIN_BY_INTAKE: Record<string, { label: string; abbr: string }> = {
  webform: { label: 'Portal', abbr: 'P' },
  drop: { label: 'Portal', abbr: 'P' },
  csv: { label: 'Email', abbr: 'E' },
  manual: { label: 'Postal mail', abbr: 'M' },
}

function channelOriginForItem(item: NeedsAttentionItem): { label: string; abbr: string } {
  return (
    CHANNEL_ORIGIN_BY_INTAKE[item.intake_source] ?? {
      label: item.intake_source,
      abbr: item.intake_source.slice(0, 1).toUpperCase() || '?',
    }
  )
}

function legalFilterEmptyMessage(filter: LegalInboxFilter | null): string {
  if (filter == null) return 'Nothing in the Legal inbox right now.'
  switch (filter) {
    case 'unassigned':
      return 'No unassigned work in this filter.'
    case 'assignment_to_legal':
      return 'No assignment-to-legal items from data owners right now.'
    case 'fulfillment':
      return 'No pre-fulfillment work — start fulfillment kickoff below when dispositions are ready.'
    case 'notice':
      return NOTICE_APPROVAL.empty
    case 'delivery':
      return 'No access delivery handoffs yet.'
    case 'pre_matching_holds':
      return 'No pre-matching holds — condition routes land here before matching.'
    case 'assigned_to_me':
      return 'No pending tasks assigned to you.'
    default:
      return 'Nothing in the Legal inbox right now.'
  }
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

type InboxWorkType =
  | 'notice'
  | 'delivery'
  | 'matching'
  | 'triage'
  | 'assignment_to_legal'
  | 'communications'
  | 'other'

const INBOX_WORK_TYPE_ORDER: InboxWorkType[] = [
  'matching',
  'triage',
  'assignment_to_legal',
  'notice',
  'delivery',
  'communications',
  'other',
]

const INBOX_WORK_TYPE_LABELS: Record<InboxWorkType, string> = {
  notice: 'Notice',
  delivery: 'Delivery',
  matching: 'Matching',
  triage: 'Pre-matching hold',
  assignment_to_legal: 'Assignment to legal',
  communications: 'Comms',
  other: 'Other',
}

const OPS_INBOX_KIND_TABS: { value: InboxKind; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'matching', label: 'Matching' },
  { value: 'triage', label: 'Triage' },
  { value: 'escalations', label: 'To legal' },
  { value: 'delivery', label: 'Delivery' },
  { value: 'notice', label: 'Notice' },
  { value: 'communications', label: 'Comms' },
  { value: 'pending_tasks', label: 'Tasks' },
]

/** Legal case queue — primary chips stay visible; secondary live in a dropdown. */
const LEGAL_INBOX_PRIMARY_FILTERS: {
  value: LegalInboxFilter
  label: string
  shortLabel: string
}[] = [
  { value: 'unassigned', label: 'Unassigned', shortLabel: 'Unassigned' },
  {
    value: 'assignment_to_legal',
    label: 'Assignment to legal',
    shortLabel: 'To legal',
  },
  { value: 'fulfillment', label: 'Fulfillment', shortLabel: 'Fulfillment' },
  { value: 'notice', label: 'Notice', shortLabel: 'Notice' },
]

const LEGAL_INBOX_MORE_FILTERS: {
  value: LegalInboxFilter
  label: string
  shortLabel: string
}[] = [
  { value: 'delivery', label: 'Delivery', shortLabel: 'Delivery' },
  {
    value: 'pre_matching_holds',
    label: 'Pre-matching holds',
    shortLabel: 'Holds',
  },
  { value: 'assigned_to_me', label: 'Assigned to me', shortLabel: 'Mine' },
]

function isAssignmentToLegalItem(item: NeedsAttentionItem): boolean {
  return (
    isEscalationItem(item) &&
    (item.assignment?.target_role === 'legal' || item.kind === 'escalations')
  )
}

function isFulfillmentLegalItem(item: NeedsAttentionItem): boolean {
  if (isTriageItem(item) || isAssignmentToLegalItem(item)) return false
  if (isNoticeItem(item) || isDeliveryItem(item)) return false
  return (
    item.reason === 'matching.review' ||
    item.current_stage === 'review' ||
    item.current_stage === 'fulfillment' ||
    item.kind === 'matching'
  )
}

function isUnassignedItem(item: NeedsAttentionItem): boolean {
  const assignee = item.assignment?.assignee_identity?.trim()
  return !assignee
}

function matchesLegalInboxFilter(
  item: NeedsAttentionItem,
  filter: LegalInboxFilter,
  myEmail?: string,
): boolean {
  switch (filter) {
    case 'unassigned':
      return isUnassignedItem(item)
    case 'assignment_to_legal':
      return isAssignmentToLegalItem(item)
    case 'fulfillment':
      return isFulfillmentLegalItem(item)
    case 'notice':
      return isNoticeItem(item)
    case 'delivery':
      return isDeliveryItem(item)
    case 'pre_matching_holds':
      return isTriageItem(item)
    case 'assigned_to_me':
      return isPendingTaskFor(item, myEmail)
    default:
      return true
  }
}

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
  return actionReasonLabel(reason)
}

function formatInboxTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}

function matchTypeLabel(matchType: string | null | undefined): string {
  if (!matchType) return 'No match data'
  if (matchType === 'single_match') return 'Single match'
  if (matchType === 'multi_match') return 'Multi-person'
  if (matchType === 'not_found') return 'Not found'
  return matchType.replaceAll('_', ' ')
}

function matchingStatusLabel(reviewStatus: string | null | undefined): string {
  const normalized = (reviewStatus ?? '').trim().toLowerCase()
  if (normalized === 'approved') return 'Approved'
  if (normalized === 'declined' || normalized === 'rejected') return 'Declined'
  if (normalized === 'pending' || normalized === '') return 'Pending'
  return normalized.replaceAll('_', ' ')
}

/** Human DROP code label — e.g. Deleted (3), Exempted (2). */
function formatDropStatusCode(code: number): string {
  const known: Record<number, string> = {
    2: 'Exempted',
    3: 'Deleted',
    4: 'Opted out',
    5: 'Not found',
  }
  const name = known[code]
  if (name) return `${name} (${code})`
  const raw = dropResponseStatusLabel(code)
  if (raw === '—' || raw === String(code)) return `Code (${code})`
  // dropResponseStatusLabel → "3 Deleted"
  const parts = raw.trim().split(/\s+/)
  if (parts.length >= 2 && parts[0] === String(code)) {
    return `${parts.slice(1).join(' ')} (${code})`
  }
  return `${raw} (${code})`
}

function resolveDropStatusCode(
  item: NeedsAttentionItem,
  matching?: MatchingResultDetail | null,
): number | null {
  if (item.response_status != null) return item.response_status
  const fromMatching = matching?.recommended_response_status
  if (fromMatching != null) return fromMatching
  if (item.recommended_response_status != null) return item.recommended_response_status
  const matchType = matching?.match_type ?? item.match_type
  const matchCount = matching?.match_count ?? item.match_count
  if (matchType != null || matchCount != null) {
    return suggestedDropResponseStatus(matchType, matchCount)
  }
  return null
}

/**
 * CA DROP response_status pill for inbox detail header.
 * Prefer actual `response_status` when present; otherwise recommended/suggested code.
 * Green when set/complete; amber when matched but not yet fulfilled; mute when unknown.
 */
function dropStatusPill(
  item: NeedsAttentionItem,
  matching?: MatchingResultDetail | null,
): { label: string; tone: 'set' | 'pending' | 'unknown' } | null {
  if (item.intake_source !== 'drop') return null
  const code = resolveDropStatusCode(item, matching)
  const hasActualStatus = item.response_status != null
  const reviewStatus = (matching?.review_status ?? item.review_status ?? '')
    .trim()
    .toLowerCase()
  const statusSet =
    hasActualStatus ||
    isNoticeItem(item) ||
    reviewStatus === 'approved' ||
    item.current_stage === 'notice' ||
    item.current_stage === 'fulfill' ||
    item.current_stage === 'delivery'
  const matchedPending =
    !statusSet &&
    (item.match_type != null ||
      matching?.match_type != null ||
      reviewStatus === 'pending' ||
      item.reason === 'matching.review' ||
      item.current_stage === 'review')

  if (statusSet && code != null) {
    return {
      label: `DROP status · ${formatDropStatusCode(code)}`,
      tone: 'set',
    }
  }
  if (code != null) {
    return {
      label: `DROP status · ${formatDropStatusCode(code)}`,
      tone: 'pending',
    }
  }
  if (matchedPending) {
    return { label: 'DROP status · pending fulfill', tone: 'pending' }
  }
  return { label: 'DROP status · unknown', tone: 'unknown' }
}

function inboxWorkType(item: NeedsAttentionItem): InboxWorkType {
  if (isNoticeItem(item)) return 'notice'
  if (isDeliveryItem(item)) return 'delivery'
  if (isAssignmentToLegalItem(item) || isEscalationItem(item)) {
    return 'assignment_to_legal'
  }
  if (isTriageItem(item)) return 'triage'
  if (isMatchingItem(item)) return 'matching'
  if (isCommsItem(item)) return 'communications'
  return 'other'
}

function buildTypeSections(
  items: NeedsAttentionItem[],
): { key: InboxWorkType; label: string; items: NeedsAttentionItem[] }[] {
  const buckets = new Map<InboxWorkType, NeedsAttentionItem[]>()
  for (const item of items) {
    const key = inboxWorkType(item)
    const list = buckets.get(key) ?? []
    list.push(item)
    buckets.set(key, list)
  }
  return INBOX_WORK_TYPE_ORDER.filter((key) => (buckets.get(key)?.length ?? 0) > 0).map(
    (key) => ({
      key,
      label: INBOX_WORK_TYPE_LABELS[key],
      items: buckets.get(key) ?? [],
    }),
  )
}

function workQueueOwnerChip(item: NeedsAttentionItem): string {
  if (isNoticeItem(item)) return 'Legal · Fulfillment notice'
  if (isDeliveryItem(item)) return 'Legal · Access delivery'
  const role = item.assignment?.target_role?.trim()
  if (role === 'legal') return 'Legal · Work queue'
  if (role) return `${role.replaceAll('_', ' ')} · Work queue`
  return 'Legal · Work queue'
}

/**
 * Inbox always exposes individual assignment (avatar picker + row owner).
 * Kept as a helper so call sites stay explicit if we reintroduce work-queue-only modes.
 */
function showInboxIndividualAssignee(
  _item: NeedsAttentionItem,
  _legalPersona: boolean,
): boolean {
  return true
}

function inboxItemTitle(item: NeedsAttentionItem): string {
  if (isTriageItem(item)) {
    const state = item.requestor_state?.trim()
    return state ? `Hold · ${state}` : 'Pre-matching hold'
  }
  if (isAssignmentToLegalItem(item)) return 'Assignment to legal'
  if (isEscalationItem(item)) return 'Assignment to legal'
  if (isDeliveryItem(item)) return 'Access delivery'
  if (isNoticeItem(item)) return 'Fulfillment notice'
  if (isCommsItem(item)) return 'Communications'
  if (isFulfillmentLegalItem(item)) return 'Pre-fulfillment'
  return reasonLabel(item.reason)
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

function formatDueWhen(item: NeedsAttentionItem): string | null {
  const due = deriveDueAt(item)
  if (!due) return null
  return due.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatDueLabel(item: NeedsAttentionItem): string {
  const when = formatDueWhen(item)
  if (!when) return 'No due date'
  const bucket = dueBucket(item)
  if (bucket === 'overdue') return `Overdue · ${when}`
  if (bucket === 'due_soon') return `Due soon · ${when}`
  return `Due ${when}`
}

/** Colored due/SLA pill for list + detail — urgency without a text dump. */
function DuePill({
  item,
  className,
}: {
  item: NeedsAttentionItem
  className?: string
}) {
  const when = formatDueWhen(item)
  if (!when) return null
  const bucket = dueBucket(item)
  const label =
    bucket === 'overdue'
      ? `Overdue · ${when}`
      : bucket === 'due_soon'
        ? `Due soon · ${when}`
        : `Due ${when}`
  return (
    <Badge
      variant={bucket === 'overdue' ? 'fail' : bucket === 'due_soon' ? 'wait' : 'default'}
      className={cn(
        'normal-case tracking-normal tabular-nums',
        bucket === 'overdue' && 'border-red-200 bg-red-50 text-red-800',
        bucket === 'due_soon' && 'border-amber-200 bg-amber-50 text-amber-900',
        className,
      )}
    >
      {label}
    </Badge>
  )
}

function InboxPaginationBar({
  start,
  end,
  total,
  currentPage,
  totalPages,
  onPrev,
  onNext,
}: {
  start: number
  end: number
  total: number
  currentPage: number
  totalPages: number
  onPrev: () => void
  onNext: () => void
}) {
  return (
    <div className="flex shrink-0 items-center justify-between gap-2 border-t border-line px-3 py-1.5 text-[0.65rem] text-ink-soft">
      <span className="tabular-nums">
        {total === 0 ? 'No items' : `${start + 1}–${end} of ${total}`}
      </span>
      {totalPages > 1 ? (
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            className="rounded border border-line bg-white px-1.5 py-0.5 text-[0.65rem] font-medium text-ink-soft transition-colors hover:bg-panel/60 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
            onClick={onPrev}
            disabled={currentPage <= 1}
          >
            Prev
          </button>
          <span className="tabular-nums text-mute">
            {currentPage}/{totalPages}
          </span>
          <button
            type="button"
            className="rounded border border-line bg-white px-1.5 py-0.5 text-[0.65rem] font-medium text-ink-soft transition-colors hover:bg-panel/60 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
            onClick={onNext}
            disabled={currentPage >= totalPages}
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  )
}

function FilterChip({
  active,
  label,
  count,
  onClick,
  compact = false,
  title,
}: {
  active: boolean
  label: string
  count?: number
  onClick: () => void
  compact?: boolean
  title?: string
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title ? (count != null ? `${title} ${count}` : title) : undefined}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onClick()
        }
      }}
      aria-pressed={active}
      className={cn(
        'inline-flex shrink-0 items-center rounded-md border font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-habeas-navy/40',
        compact
          ? 'gap-1 px-1.5 py-0.5 text-[0.65rem]'
          : 'gap-1.5 px-2.5 py-1 text-[0.7rem]',
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

type AssignTarget =
  | { kind: 'user'; email: string }
  | { kind: 'group'; group: 'legal' | 'data' }

function assigneeDisplayLabel(
  currentEmail: string | null | undefined,
  currentGroup: 'legal' | 'data' | null | undefined,
): string {
  if (currentEmail?.trim()) return currentEmail.trim()
  if (currentGroup === 'legal') return 'Legal team'
  if (currentGroup === 'data') return 'Data team'
  return 'Unassigned'
}

function AssigneeAvatarPicker({
  currentEmail,
  currentGroup,
  candidates,
  disabled,
  pending,
  error,
  onAssign,
}: {
  currentEmail: string | null | undefined
  currentGroup?: 'legal' | 'data' | null
  candidates: string[]
  disabled: boolean
  pending: boolean
  error: string | null
  onAssign: (target: AssignTarget) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const label = assigneeDisplayLabel(currentEmail, currentGroup)
  const assigned = label !== 'Unassigned'
  const normalizedQuery = query.trim().toLowerCase()
  const predicted = (
    normalizedQuery
      ? candidates.filter((email) => email.toLowerCase().includes(normalizedQuery))
      : candidates
  ).slice(0, 12)
  const exactMatch = Boolean(
    normalizedQuery &&
      candidates.some((email) => email.toLowerCase() === normalizedQuery),
  )
  const canAssignTyped =
    normalizedQuery.includes('@') && normalizedQuery.length >= 3 && !exactMatch

  return (
    <div className="flex items-center gap-2">
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          if (!next) setQuery('')
        }}
      >
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
            aria-label={assigned ? `Assigned to ${label}` : 'Assign reviewer'}
          >
            <Avatar className="h-7 w-7">
              <AvatarFallback>
                {currentGroup === 'legal'
                  ? 'LG'
                  : currentGroup === 'data'
                    ? 'DT'
                    : emailInitials(currentEmail)}
              </AvatarFallback>
            </Avatar>
            <span className="min-w-0 max-w-[10rem]">
              <span className="block text-[0.6rem] text-mute">Assignee</span>
              <span className="block truncate text-[0.7rem] font-medium text-ink">
                {label}
              </span>
            </span>
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-80 p-2" align="start">
          <p className="px-1.5 pb-1.5 text-[0.65rem] text-mute">
            Assign a person or team queue
          </p>
          <input
            className="mb-2 w-full rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search people…"
            aria-label="Search assignees"
            autoFocus
            onKeyDown={(event) => {
              if (event.key === 'Enter' && canAssignTyped) {
                onAssign({ kind: 'user', email: query.trim() })
                setQuery('')
                setOpen(false)
              } else if (event.key === 'Enter' && predicted.length === 1) {
                onAssign({ kind: 'user', email: predicted[0] })
                setQuery('')
                setOpen(false)
              }
            }}
          />
          <div className="mb-2 space-y-0.5 border-b border-line pb-2">
            <p className="px-1.5 pb-1 text-[0.6rem] font-medium uppercase tracking-wide text-mute">
              Teams
            </p>
            {(
              [
                {
                  group: 'legal' as const,
                  title: 'Legal',
                  hint: 'Anyone on the Legal team',
                },
                {
                  group: 'data' as const,
                  title: 'Data',
                  hint: 'Anyone on the Data team',
                },
              ] as const
            ).map((team) => {
              const selected = currentGroup === team.group && !currentEmail
              return (
                <button
                  key={team.group}
                  type="button"
                  className={cn(
                    'flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-xs',
                    selected
                      ? 'bg-habeas-navy/10 text-habeas-navy'
                      : 'hover:bg-panel/60',
                  )}
                  disabled={pending}
                  onClick={() => {
                    onAssign({ kind: 'group', group: team.group })
                    setOpen(false)
                  }}
                >
                  <Avatar className="h-6 w-6">
                    <AvatarFallback className="text-[0.55rem]">
                      {team.group === 'legal' ? 'LG' : 'DT'}
                    </AvatarFallback>
                  </Avatar>
                  <span className="min-w-0">
                    <span className="block font-medium">{team.title}</span>
                    <span className="block text-[0.6rem] text-mute">{team.hint}</span>
                  </span>
                </button>
              )
            })}
          </div>
          <p className="px-1.5 pb-1 text-[0.6rem] font-medium uppercase tracking-wide text-mute">
            People
          </p>
          <ul className="max-h-44 space-y-0.5 overflow-y-auto">
            {predicted.map((email) => {
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
                      onAssign({ kind: 'user', email })
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
            {predicted.length === 0 && !canAssignTyped ? (
              <li className="px-1.5 py-2 text-[0.65rem] text-mute">
                {normalizedQuery
                  ? 'No matching people. Type a full email to assign.'
                  : 'No known reviewers yet.'}
              </li>
            ) : null}
            {canAssignTyped ? (
              <li>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-xs hover:bg-panel/60"
                  disabled={pending}
                  onClick={() => {
                    onAssign({ kind: 'user', email: query.trim() })
                    setQuery('')
                    setOpen(false)
                  }}
                >
                  <Avatar className="h-6 w-6">
                    <AvatarFallback className="text-[0.55rem]">+</AvatarFallback>
                  </Avatar>
                  <span className="min-w-0 truncate">Assign {query.trim()}</span>
                </button>
              </li>
            ) : null}
          </ul>
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

export function ChannelOriginAvatar({ item }: { item: NeedsAttentionItem }) {
  const channel = channelOriginForItem(item)
  return (
    <span className="relative inline-flex shrink-0" title={`Channel: ${channel.label}`}>
      <Avatar className="h-5 w-5">
        <AvatarFallback className="text-[0.45rem] text-mute">?</AvatarFallback>
      </Avatar>
      <span
        className="absolute -bottom-0.5 -right-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-full border border-paper bg-habeas-navy px-0.5 text-[0.4rem] font-semibold leading-none text-white tabular-nums"
        aria-label={channel.label}
      >
        {channel.abbr}
      </span>
    </span>
  )
}

type LegalComposerOption = {
  id: string
  label: string
  hint: string
  requiresBody?: boolean
  run: (body: string) => Promise<void>
}

function buildLegalComposerOptions(
  item: NeedsAttentionItem,
  myEmail?: string,
): LegalComposerOption[] {
  const options: LegalComposerOption[] = []

  if (isTriageItem(item)) {
    options.push(
      {
        id: 'triage_reject',
        label: 'Reject as Exempted',
        hint: 'Set DROP response_status 2 and release pre-matching hold',
        run: async (body) => {
          if (body.trim()) await postRequestComment(item.request_id, body.trim())
          await postTriageBulkReject({ request_ids: [item.request_id], response_status: 2 })
        },
      },
      {
        id: 'triage_match',
        label: 'Send to matching',
        hint: 'Release hold and enqueue automatic matching',
        run: async (body) => {
          if (body.trim()) await postRequestComment(item.request_id, body.trim())
          await postTriageSendToMatching({ request_ids: [item.request_id] })
        },
      },
    )
  }

  if (isNoticeItem(item)) {
    options.push({
      id: 'notice_approve',
      label: NOTICE_APPROVAL.action,
      hint: NOTICE_APPROVAL.hint,
      run: async (body) => {
        if (body.trim()) await postRequestComment(item.request_id, body.trim())
        await postNoticeApprove({ request_ids: [item.request_id] })
      },
    })
  }

  if (isDeliveryItem(item)) {
    options.push(
      {
        id: 'delivery_delivered',
        label: 'Confirm delivered',
        hint: 'Mark access pack delivery as delivered',
        run: async (body) => {
          if (body.trim()) await postRequestComment(item.request_id, body.trim())
          await patchAccessDeliveryStatus(item.request_id, { status: 'delivered' })
        },
      },
      {
        id: 'delivery_failed',
        label: 'Mark delivery failed',
        hint: 'Record failed delivery attempt',
        run: async (body) => {
          if (body.trim()) await postRequestComment(item.request_id, body.trim())
          await patchAccessDeliveryStatus(item.request_id, { status: 'failed' })
        },
      },
    )
  }

  if (isAssignmentToLegalItem(item)) {
    options.push({
      id: 'assignment_review',
      label: 'Record legal review note',
      hint: 'Log review context — kickoff lives in the next-step card when dispositions are ready',
      requiresBody: true,
      run: async (body) => {
        if (!body.trim()) throw new Error('Reply is required for review notes')
        await postRequestComment(item.request_id, body.trim())
      },
    })
  } else if (isFulfillmentLegalItem(item)) {
    options.push({
      id: 'fulfillment_note',
      label: 'Record pre-fulfillment note',
      hint: 'Log identity verification or kickoff context',
      requiresBody: true,
      run: async (body) => {
        if (!body.trim()) throw new Error('Reply is required for pre-fulfillment notes')
        await postRequestComment(item.request_id, body.trim())
      },
    })
  }

  if (!item.assignment?.assignee_identity?.trim() && myEmail) {
    options.push({
      id: 'take_it',
      label: 'Take it — claim assignment',
      hint: 'Assign this request to you',
      run: async (body) => {
        if (body.trim()) await postRequestComment(item.request_id, body.trim())
        await postDropWorkflowAssign({
          request_ids: [item.request_id],
          assignee_identity: myEmail,
          target_role: 'reviewer',
        })
      },
    })
  }

  if (options.length === 0) {
    options.push({
      id: 'inbox_note',
      label: 'Record inbox note',
      hint: 'Add correspondence with paired status',
      requiresBody: true,
      run: async (body) => {
        if (!body.trim()) throw new Error('Reply is required')
        await postRequestComment(item.request_id, body.trim())
      },
    })
  }

  return options
}

export function LegalInboxComposer({
  item,
  canReviewActions,
  myEmail,
  onSuccess,
}: {
  item: NeedsAttentionItem
  canReviewActions: boolean
  myEmail?: string
  onSuccess: () => Promise<void>
}) {
  const options = useMemo(
    () => buildLegalComposerOptions(item, myEmail),
    [item, myEmail],
  )
  const [statusId, setStatusId] = useState(() => options[0]?.id ?? '')
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!options.some((option) => option.id === statusId)) {
      setStatusId(options[0]?.id ?? '')
    }
  }, [options, statusId])

  const selected = options.find((option) => option.id === statusId) ?? options[0]
  const sendMutation = useMutation({
    mutationFn: async ({
      statusId: nextStatusId,
      body: nextBody,
    }: {
      statusId: string
      body: string
    }) => {
      const option = options.find((candidate) => candidate.id === nextStatusId)
      if (!option) throw new Error('Select a status transition')
      if (option.requiresBody && !nextBody.trim()) {
        throw new Error('Reply is required for this status')
      }
      await option.run(nextBody)
    },
    onSuccess: async () => {
      setError(null)
      setBody('')
      actionToast.success({ title: 'Status updated' })
      await onSuccess()
    },
    onError: (mutationError, variables) => {
      const message =
        mutationError instanceof Error ? mutationError.message : ''
      if (
        message === 'Select a status transition' ||
        message === 'Reply is required for this status'
      ) {
        setError(message)
        return
      }
      setError(null)
      actionToast.error({
        title: 'Status update failed',
        description: actionToast.safeErrorMessage(mutationError),
        action: {
          label: 'Retry',
          onClick: () => sendMutation.mutate(variables),
        },
      })
    },
  })

  if (!canReviewActions || !selected) return null

  return (
    <div className="space-y-2 border-t border-line pt-2">
      <label className="flex flex-col gap-1 text-[0.65rem] text-ink-soft">
        Status transition
        <select
          className="rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
          value={statusId}
          onChange={(event) => setStatusId(event.target.value)}
          disabled={sendMutation.isPending}
          aria-label="Status transition"
        >
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {selected.hint ? <p className="text-[0.65rem] text-mute">{selected.hint}</p> : null}
      <textarea
        className="min-h-[2.5rem] max-h-20 w-full resize-y rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
        value={body}
        onChange={(event) => setBody(event.target.value)}
        placeholder={
          selected.requiresBody
            ? 'Reply required — persists to correspondence…'
            : 'Optional reply — persists to correspondence…'
        }
        aria-label="Reply body"
        maxLength={2000}
        disabled={sendMutation.isPending}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          disabled={
            sendMutation.isPending ||
            !statusId ||
            (selected.requiresBody === true && body.trim().length === 0)
          }
          onClick={() => sendMutation.mutate({ statusId, body: body.trim() })}
        >
          {sendMutation.isPending ? 'Sending…' : 'Send and advance'}
        </Button>
      </div>
      {error ? <p className="text-[0.65rem] text-red-700">{error}</p> : null}
    </div>
  )
}

function inboxItemToSeedRequest(item: NeedsAttentionItem): RequestRecord {
  return {
    id: item.request_id,
    received_at: item.received_at ?? item.requested_at ?? '',
    intake_source: item.intake_source as IntakeSource,
    raw_record_id: null,
    requestor_state: item.requestor_state,
  }
}

type InboxActivityFilter = 'all' | 'notes' | 'system'

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

function humanizeActivitySummary(summary: string): string {
  return summary.replace(
    /\b[\w]+(?:\.[\w]+)+\b/g,
    (match) => actionReasonLabel(match),
  )
}

/** Compact Activity timeline for Inbox split-view detail (mirrors overlay, denser). */
function InboxActivityPanel({
  requestId,
  canCompose,
}: {
  requestId: string
  canCompose: boolean
}) {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<InboxActivityFilter>('all')
  const [comment, setComment] = useState('')

  const timelineQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'timeline'],
    queryFn: () => getRequestTimeline(requestId),
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const commentMutation = useMutation({
    mutationFn: () => postRequestComment(requestId, comment.trim()),
    onSuccess: async () => {
      setComment('')
      actionToast.success({ title: 'Note posted' })
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['admin-api', 'ops', 'requests', requestId, 'timeline'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['admin-api', 'ops', 'requests', requestId, 'comments'],
        }),
      ])
    },
    onError: (err) => {
      actionToast.error({
        title: 'Note failed',
        description: actionToast.safeErrorMessage(err),
        action: {
          label: 'Retry',
          onClick: () => commentMutation.mutate(),
        },
      })
    },
  })

  const entries = timelineQuery.data?.entries ?? []
  const filtered = entries.filter((entry) => {
    const human = isHumanActivityKind(entry.kind)
    if (filter === 'notes') return human
    if (filter === 'system') return !human
    return true
  })

  const filters: { id: InboxActivityFilter; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'notes', label: 'Notes & assignment' },
    { id: 'system', label: 'System' },
  ]

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-1.5">
        <p className="text-[0.6rem] font-medium uppercase tracking-wide text-mute">
          Activity
        </p>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Activity filter">
          {filters.map((item) => (
            <button
              key={item.id}
              type="button"
              className={cn(
                'rounded border px-1.5 py-0.5 text-[0.6rem] transition-colors',
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

      {timelineQuery.isPending && !timelineQuery.data ? (
        <SkeletonLines lines={3} />
      ) : null}
      {timelineQuery.isError ? (
        <p className="text-[0.7rem] text-red-700">Could not load activity.</p>
      ) : null}
      {!timelineQuery.isPending && !timelineQuery.isError && filtered.length === 0 ? (
        <p className="text-[0.7rem] text-mute">
          {entries.length === 0
            ? 'No activity yet.'
            : 'No matching activity for this filter.'}
        </p>
      ) : null}

      <ol className="min-h-[12rem] space-y-1">
        {filtered.map((entry: TimelineEntry, index) => {
          const human = isHumanActivityKind(entry.kind)
          const kindLabel = activityKindLabel(entry.kind)
          const summary = humanizeActivitySummary(entry.summary)

          if (!human) {
            return (
              <li
                key={`${entry.at}-${entry.kind}-${index}`}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-0.5 text-[0.65rem] text-mute"
              >
                <time className="shrink-0 tabular-nums">
                  {formatInboxTimestamp(entry.at)}
                </time>
                <span className="min-w-0 text-ink-soft">{summary}</span>
              </li>
            )
          }

          return (
            <li
              key={`${entry.at}-${entry.kind}-${index}`}
              className="rounded-md border border-line/80 bg-paper/70 px-2 py-1.5 text-[0.7rem]"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-1">
                <div className="flex min-w-0 flex-wrap items-center gap-1">
                  {kindLabel ? (
                    <Badge variant="wait" className="normal-case tracking-normal">
                      {kindLabel}
                    </Badge>
                  ) : null}
                  <span className="font-medium text-ink">
                    {entry.actor?.trim() || 'Operator'}
                  </span>
                </div>
                <time className="shrink-0 tabular-nums text-[0.6rem] text-mute">
                  {formatInboxTimestamp(entry.at)}
                </time>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-ink">{summary}</p>
            </li>
          )
        })}
      </ol>

      {canCompose ? (
        <div className="space-y-1.5 border-t border-line pt-2">
          <textarea
            className="min-h-[3.5rem] max-h-32 w-full resize-y rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
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
        </div>
      ) : null}
    </div>
  )
}

const INBOX_DETAIL_TAB_TRIGGER =
  'h-7 rounded-md border border-transparent px-2.5 text-[0.7rem] data-[state=active]:border-habeas-navy/25 data-[state=active]:bg-white data-[state=active]:text-habeas-navy data-[state=active]:shadow-sm'

/** Dense ops summary for Inbox Overview tab — request + process context. */
function RequestProcessSummary({
  item,
  matching,
  identity,
  identityPending,
  legalPersona = false,
}: {
  item: NeedsAttentionItem
  matching?: MatchingResultDetail | null
  identity?: IdentityVerificationRecord | null
  identityPending?: boolean
  legalPersona?: boolean
}) {
  const channel = SOURCE_LABELS[item.intake_source] ?? item.intake_source
  const matchType = matching?.match_type ?? item.match_type
  const matchCount = matching?.match_count ?? item.match_count
  const recommended =
    matching?.recommended_response_status ?? item.recommended_response_status
  const reviewStatus = matching?.review_status ?? item.review_status
  const assignee = item.assignment?.assignee_identity
  const ownerRole = item.assignment?.target_role

  let ownerValue = 'Unassigned'
  if (!showInboxIndividualAssignee(item, legalPersona)) {
    ownerValue = workQueueOwnerChip(item)
  } else if (assignee) {
    ownerValue = ownerRole
      ? `${assignee} · ${ownerRole.replaceAll('_', ' ')}`
      : assignee
  } else if (ownerRole) {
    ownerValue = ownerRole.replaceAll('_', ' ')
  }

  let identityValue: string
  if (identityPending && !identity) {
    identityValue = 'Loading…'
  } else if (identity) {
    const parts = [
      identity.status,
      identity.method,
      formatInboxTimestamp(identity.verified_at),
      identity.verified_by,
    ].filter(Boolean)
    identityValue = parts.join(' · ')
  } else {
    identityValue = 'None recorded'
  }

  const rows: { label: string; value: ReactNode; fullWidth?: boolean }[] = [
    { label: 'Channel', value: channel },
    { label: 'Due', value: <DuePill item={item} /> },
    { label: 'Owner', value: ownerValue },
    { label: 'Identity', value: identityValue, fullWidth: true },
  ]
  if (matchType || reviewStatus) {
    rows.push({
      label: 'Matching',
      value: [
        matchType ? matchTypeLabel(matchType) : null,
        matchCount != null ? `${matchCount} matches` : null,
        matchingStatusLabel(reviewStatus),
      ]
        .filter(Boolean)
        .join(' · '),
    })
  }
  if (recommended != null) {
    rows.push({
      label: 'DROP response',
      value: formatDropStatusCode(recommended),
    })
  }

  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3">
      {rows.map((row) => (
        <div
          key={row.label}
          className={cn('min-w-0', row.fullWidth && 'col-span-2 sm:col-span-3')}
        >
          <dt className="text-[0.6rem] text-mute">{row.label}</dt>
          <dd
            className={cn(
              'mt-0.5 text-[0.7rem] text-ink',
              row.fullWidth ? 'whitespace-normal break-words' : 'truncate',
            )}
            title={typeof row.value === 'string' ? row.value : undefined}
          >
            {row.value ?? '—'}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function InboxReviewPane({
  item,
  canReviewActions,
  assigneeCandidates,
  legalPersona = false,
  onBackToQueue,
  onOpenDetail,
}: {
  item: NeedsAttentionItem
  canReviewActions: boolean
  assigneeCandidates: string[]
  /** Legal case-queue mode — no matching disposition; status-required composer. */
  legalPersona?: boolean
  onBackToQueue?: () => void
  onOpenDetail?: (item: NeedsAttentionItem, trigger: HTMLElement) => void
}) {
  const queryClient = useQueryClient()
  const { me } = useMe()
  const [commentDraft, setCommentDraft] = useState('')
  const [confirmAction, setConfirmAction] = useState<
    | 'fulfill'
    | 'decline'
    | 'escalate'
    | 'triage_reject'
    | 'triage_match'
    | 'notice_approve'
    | null
  >(null)
  const isAccessRequest = useIsAccessRequest(item.request_id)

  const showTriage = isTriageItem(item)
  const showAssignmentToLegal = legalPersona && isAssignmentToLegalItem(item)
  const showMatching =
    isMatchingItem(item) &&
    !isDeliveryItem(item) &&
    !isNoticeItem(item) &&
    !showTriage &&
    !legalPersona
  const showDelivery = isDeliveryItem(item) || item.current_stage === 'fulfill'
  const showNotice = isNoticeItem(item)
  const showComms = isCommsItem(item) && !legalPersona

  // Matching detail for review + notice (post-fulfill summary still needs match info).
  const matchingQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop', 'matching-results', item.request_id],
    queryFn: () => fetchMatchingDetailOptional(item.request_id),
    enabled: true,
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'journey'],
    queryFn: () => getRequestJourney(item.request_id),
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const workbenchQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'journey-workbench'],
    queryFn: async () => {
      try {
        return await getRequestJourneyWorkbench(item.request_id)
      } catch (error) {
        if (error instanceof Error && /Admin API 404/.test(error.message)) {
          return null
        }
        throw error
      }
    },
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
    retry: false,
  })

  const artifactQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', item.request_id],
    queryFn: () => getFulfillmentArtifact(item.request_id),
    refetchInterval: 15_000,
    retry: false,
  })

  const identityQuery = useQuery({
    queryKey: ['admin-api', 'requests', item.request_id, 'identity-verification'],
    queryFn: () => getLatestIdentityVerification(item.request_id),
    refetchInterval: 15_000,
    retry: false,
  })

  const commentsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'comments'],
    queryFn: () => getRequestComments(item.request_id),
    refetchInterval: 15_000,
  })

  const requestQuery = useQuery({
    queryKey: ['admin-api', 'requests', item.request_id],
    queryFn: () => getRequest(item.request_id),
    refetchInterval: 30_000,
    placeholderData: (previous) => previous,
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
      setConfirmAction(null)
      actionToast.success({ title: 'Request fulfilled' })
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Fulfill failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => promoteMutation.mutate(variables),
        },
      })
    },
  })

  const declineMutation = useMutation({
    mutationFn: () => postDropMatchingResultDecline(item.request_id),
    onSuccess: async () => {
      actionToast.success({ title: 'Matching review declined' })
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Decline failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => declineMutation.mutate(),
        },
      })
    },
  })

  const escalateMutation = useMutation({
    mutationFn: () =>
      postDropWorkflowEscalate({
        request_ids: [item.request_id],
        target_role: 'legal',
      }),
    onSuccess: async () => {
      setConfirmAction(null)
      actionToast.success({ title: 'Assigned to legal' })
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Assign to legal failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => escalateMutation.mutate(),
        },
      })
    },
  })

  const triageRejectMutation = useMutation({
    mutationFn: () =>
      postTriageBulkReject({
        request_ids: [item.request_id],
        response_status: 2,
      }),
    onSuccess: async () => {
      setConfirmAction(null)
      actionToast.success({ title: 'Rejected as exempted' })
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Triage reject failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => triageRejectMutation.mutate(),
        },
      })
    },
  })

  const triageMatchMutation = useMutation({
    mutationFn: () =>
      postTriageSendToMatching({ request_ids: [item.request_id] }),
    onSuccess: async () => {
      setConfirmAction(null)
      actionToast.success({ title: 'Sent to matching' })
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Send to matching failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => triageMatchMutation.mutate(),
        },
      })
    },
  })

  const noticeApproveMutation = useMutation({
    mutationFn: () => postNoticeApprove({ request_ids: [item.request_id] }),
    onSuccess: async () => {
      setConfirmAction(null)
      actionToast.success({ title: NOTICE_APPROVAL.action })
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Notice approve failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => noticeApproveMutation.mutate(),
        },
      })
    },
  })

  const assignMutation = useMutation({
    mutationFn: (target: AssignTarget) => {
      if (target.kind === 'group') {
        return postDropWorkflowEscalate({
          request_ids: [item.request_id],
          target_role: target.group === 'legal' ? 'legal' : 'data_owner',
        })
      }
      return postDropWorkflowAssign({
        request_ids: [item.request_id],
        assignee_identity: target.email,
        target_role: 'reviewer',
      })
    },
    onSuccess: async (_data, target) => {
      actionToast.success({ title: 'Assignment updated' })
      // Optimistic: notice/delivery lanes historically omitted assignment on
      // refresh — patch the inbox cache so Assignee updates immediately.
      queryClient.setQueriesData(
        { queryKey: ['admin-api', 'ops', 'requests', 'needs-attention'] },
        (previous: { items?: NeedsAttentionItem[] } | undefined) => {
          if (!previous?.items) return previous
          return {
            ...previous,
            items: previous.items.map((row) => {
              if (row.request_id !== item.request_id) return row
              if (target.kind === 'group') {
                return {
                  ...row,
                  assignment: {
                    kind: 'escalate',
                    target_role: target.group === 'legal' ? 'legal' : 'data_owner',
                    assignee_identity: null,
                  },
                }
              }
              return {
                ...row,
                assignment: {
                  kind: 'assign',
                  target_role: 'reviewer',
                  assignee_identity: target.email,
                },
              }
            }),
          }
        },
      )
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'requests', 'needs-attention'],
      })
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Assign failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => assignMutation.mutate(variables),
        },
      })
    },
  })

  const commentMutation = useMutation({
    mutationFn: (body: string) => postRequestComment(item.request_id, body),
    onSuccess: async () => {
      setCommentDraft('')
      actionToast.success({ title: 'Comment posted' })
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'comments'],
      })
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Comment failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => commentMutation.mutate(variables),
        },
      })
    },
  })

  const deliveryMutation = useMutation({
    mutationFn: (status: 'delivered' | 'failed' | 'recalled') =>
      patchAccessDeliveryStatus(item.request_id, { status }),
    onSuccess: async () => {
      actionToast.success({ title: 'Delivery status updated' })
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', item.request_id],
        }),
        queryClient.invalidateQueries({
          queryKey: ['admin-api', 'ops', 'requests', 'needs-attention'],
        }),
      ])
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Delivery update failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => deliveryMutation.mutate(variables),
        },
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
  const assignee = item.assignment?.assignee_identity
  const assignmentGroup =
    !assignee && item.assignment?.target_role === 'legal'
      ? ('legal' as const)
      : !assignee && item.assignment?.target_role === 'data_owner'
        ? ('data' as const)
        : null
  const stages = journeyQuery.data?.stages ?? []
  const derivedChrome = journeyQuery.data
    ? deriveWorkbenchChromeFromOpsJourney({
        stages: journeyQuery.data.stages,
        current_stage: journeyQuery.data.current_stage,
        intake_source: item.intake_source,
        request_type: requestQuery.data?.request_type ?? null,
      })
    : null
  const workbench = workbenchQuery.data
  const pipelineStages = workbench?.stages ?? derivedChrome?.stages ?? []
  const pipelineSubsteps = workbench
    ? derivedChrome?.substeps.filter(
        (step) => step.parent === 'ingest' || step.parent === 'notice',
      )
    : derivedChrome?.substeps
  const shareableUrl =
    artifactQuery.data?.shareable_url ?? artifactQuery.data?.fulfillment_artifact_uri ?? ''
  const showHandoffTab = showDelivery || showComms
  const showResolveMatching = showMatching || showAssignmentToLegal
  const dropPill = dropStatusPill(item, matchingQuery.data)
  /** Work-type tabs only when they hold tools — notice CTA lives in the next-step card. */
  const primaryTab = showTriage
    ? 'triage'
    : showAssignmentToLegal
      ? 'matching'
      : showMatching
        ? 'matching'
        : showHandoffTab
          ? 'delivery'
          : 'overview'

  const currentStageLabel =
    stages.find(
      (stage) =>
        stage.status === 'in_progress' ||
        stage.status === 'waiting' ||
        stage.status === 'failed',
    )?.label ?? stages[stages.length - 1]?.label

  const nextStepHint = showNotice
    ? 'Approve so this fulfilled DROP row can enter the weekly upload batch.'
    : showDelivery
      ? 'Send the access pack, then mark delivery status.'
      : showTriage
        ? 'Reject as exempted, or release to matching for the data owner.'
        : showMatching
          ? 'Confirm the match disposition, or send to legal if you need help.'
          : showAssignmentToLegal
            ? 'Review matching context, then continue pre-fulfillment work.'
            : legalPersona && isFulfillmentLegalItem(item)
              ? 'Matching approve alone does not start the worker — kick off fulfillment for each disposed vertical.'
              : null

  const kickoffRows = workbench?.fulfillment_cluster ?? []
  const showLegalKickoff =
    legalPersona &&
    canReviewActions &&
    kickoffRows.some(
      (row) =>
        row.actionable &&
        !row.kicked_off &&
        row.disposition_status != null,
    )
  const showLegalIdentityGate =
    legalPersona &&
    canReviewActions &&
    kickoffRows.some(
      (row) => row.identity_required && row.identity_verified !== true,
    )

  function copyShareableUrl() {
    if (!shareableUrl) return
    const copyAgain = () => {
      void navigator.clipboard.writeText(shareableUrl).then(() => {
        actionToast.copied('Copied URL', copyAgain)
      })
    }
    copyAgain()
  }

  return (
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
          title="Assignment to legal?"
          description={`Send request ${item.request_id.slice(0, 8)}… to Legal Inbox · Assignment to legal. Add a comment first if context is needed.`}
          confirmLabel="Assign to legal"
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
          title={NOTICE_APPROVAL.confirmTitle}
          description={`${NOTICE_APPROVAL.hint} (${item.request_id.slice(0, 8)}…).`}
          confirmLabel={NOTICE_APPROVAL.action}
          confirming={actionPending && confirmAction === 'notice_approve'}
          onConfirm={() => noticeApproveMutation.mutate()}
        />

        <div className="shrink-0 space-y-2 border-b border-line px-4 py-2.5">
          {onBackToQueue ? (
            <button
              type="button"
              onClick={onBackToQueue}
              className="text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline md:hidden"
            >
              ← Queue
            </button>
          ) : null}

          {/* 1. Identity — what this is */}
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1 space-y-0.5">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold text-ink">{inboxItemTitle(item)}</h2>
                <DuePill item={item} />
              </div>
              <p className="font-mono text-[0.65rem] text-ink-soft">
                {item.request_id}
                <span className="font-sans text-mute">
                  {' '}
                  · {SOURCE_LABELS[item.intake_source] ?? item.intake_source}
                </span>
              </p>
              {currentStageLabel ? (
                <p className="text-[0.65rem] text-mute">{currentStageLabel}</p>
              ) : null}
            </div>
            <AssigneeAvatarPicker
              currentEmail={assignee}
              currentGroup={assignmentGroup}
              candidates={assigneeCandidates}
              disabled={!canReviewActions}
              pending={assignMutation.isPending}
              error={null}
              onAssign={(target) => assignMutation.mutate(target)}
            />
          </div>

          {/* 2. Next step — one clear job for the eye */}
          {nextStepHint || canReviewActions ? (
            <div className="rounded-md border border-habeas-navy/20 bg-habeas-navy/[0.03] px-3 py-2">
              {nextStepHint ? (
                <p className="text-[0.7rem] leading-snug text-ink-soft">{nextStepHint}</p>
              ) : null}
              {showLegalKickoff || showLegalIdentityGate ? (
                <div className={cn(nextStepHint && 'mt-1.5')}>
                  <FulfillmentGateControls
                    requestId={item.request_id}
                    rows={kickoffRows}
                    onInvalidate={async () => {
                      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
                    }}
                  />
                </div>
              ) : null}
              <div className={cn('flex flex-wrap items-center gap-2', nextStepHint && 'mt-1.5')}>
                {showNotice && canReviewActions ? (
                  <Button
                    type="button"
                    size="sm"
                    disabled={actionPending}
                    onClick={() => setConfirmAction('notice_approve')}
                    title={NOTICE_APPROVAL.hint}
                    aria-label={NOTICE_APPROVAL.action}
                  >
                    {NOTICE_APPROVAL.action}
                  </Button>
                ) : null}
                {showTriage && canReviewActions ? (
                  <>
                    <Button
                      type="button"
                      size="sm"
                      disabled={actionPending}
                      onClick={() => setConfirmAction('triage_match')}
                    >
                      Send to matching
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={actionPending}
                      onClick={() => setConfirmAction('triage_reject')}
                    >
                      Reject exempted
                    </Button>
                  </>
                ) : null}
                {showMatching && canReviewActions && !legalPersona ? (
                  <>
                    <Button
                      type="button"
                      size="sm"
                      disabled={actionPending}
                      onClick={() => setConfirmAction('fulfill')}
                    >
                      Fulfill
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={actionPending}
                      onClick={() => setConfirmAction('decline')}
                    >
                      Decline
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={actionPending}
                      onClick={() => setConfirmAction('escalate')}
                    >
                      Assign to legal
                    </Button>
                  </>
                ) : null}
                {showDelivery && canReviewActions ? (
                  <>
                    {shareableUrl ? (
                      <Button
                        type="button"
                        size="sm"
                        onClick={copyShareableUrl}
                      >
                        Copy URL
                      </Button>
                    ) : null}
                  </>
                ) : null}
                <button
                  type="button"
                  className="text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline"
                  aria-label="See more details"
                  onClick={(event) => {
                    onOpenDetail?.(item, event.currentTarget)
                  }}
                >
                  See more details
                </button>
              </div>
            </div>
          ) : null}
        </div>

        {/* Thin four-stage pipeline + type/source substeps (list rows stay strip-free — R1/AE5) */}
        {pipelineStages.length > 0 ? (
          <div className="shrink-0 border-b border-line px-4 py-2">
            <ThinJourneyPipeline
              stages={pipelineStages}
              substeps={pipelineSubsteps}
              matchingCluster={workbench?.matching_cluster}
              fulfillmentCluster={workbench?.fulfillment_cluster}
              splitPosture={workbench?.split_posture ?? derivedChrome?.split_posture}
              density="compact"
            />
          </div>
        ) : null}

        <Tabs
          key={item.request_id}
          defaultValue={primaryTab}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <div className="shrink-0 border-b border-line px-4 py-1.5">
            <TabsList
              className="h-8 w-full justify-start gap-1 overflow-x-auto rounded-md border border-line bg-canvas p-0.5"
              aria-label="Request detail sections"
            >
              <TabsTrigger value="overview" className={INBOX_DETAIL_TAB_TRIGGER}>
                Overview
              </TabsTrigger>
              {showTriage ? (
                <TabsTrigger value="triage" className={INBOX_DETAIL_TAB_TRIGGER}>
                  Triage
                </TabsTrigger>
              ) : null}
              {showResolveMatching ? (
                <TabsTrigger value="matching" className={INBOX_DETAIL_TAB_TRIGGER}>
                  Matching
                </TabsTrigger>
              ) : null}
              {showHandoffTab ? (
                <TabsTrigger value="delivery" className={INBOX_DETAIL_TAB_TRIGGER}>
                  {showDelivery ? 'Delivery' : 'Handoff'}
                </TabsTrigger>
              ) : null}
              {showComms && showDelivery ? (
                <TabsTrigger value="comms" className={INBOX_DETAIL_TAB_TRIGGER}>
                  Comms
                </TabsTrigger>
              ) : null}
              {isAccessRequest === true ? (
                <TabsTrigger value="access-email" className={INBOX_DETAIL_TAB_TRIGGER}>
                  Access email
                </TabsTrigger>
              ) : null}
              <TabsTrigger value="activity" className={INBOX_DETAIL_TAB_TRIGGER}>
                Activity
              </TabsTrigger>
              <TabsTrigger
                value="comments"
                className={cn(INBOX_DETAIL_TAB_TRIGGER, 'gap-1')}
              >
                {showAssignmentToLegal ? 'Assignment thread' : 'Comments'}
                {comments.length > 0 ? (
                  <span className="tabular-nums opacity-70">({comments.length})</span>
                ) : null}
              </TabsTrigger>
            </TabsList>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            <TabsContent value="overview" className="mt-0 space-y-3">
              {showNotice ? (
                <p className="text-[0.75rem] text-ink-soft">
                  After approval, this row enters the next weekly DROP upload batch
                  (America/Los_Angeles) — not a consumer delivery URL.
                </p>
              ) : null}
              {dropPill && dropPill.tone !== 'unknown' ? (
                <Badge
                  variant={dropPill.tone === 'set' ? 'ok' : 'default'}
                  className={cn(
                    'normal-case tracking-normal',
                    dropPill.tone === 'pending' &&
                      'border-amber-200 bg-amber-50 text-amber-900',
                  )}
                >
                  {dropPill.label}
                </Badge>
              ) : null}
              <RequesterContactSection
                intakeSource={item.intake_source}
                displayLabel={requestQuery.data?.display_label}
                requestContact={requestQuery.data?.contact}
                matching={matchingQuery.data}
                dropPreMatch={
                  item.intake_source === 'drop' &&
                  matchingQuery.data == null &&
                  (item.current_stage === 'received' ||
                    item.current_stage === 'download' ||
                    item.current_stage === 'land' ||
                    item.current_stage === 'promote' ||
                    item.current_stage === 'match')
                }
                compact
              />
              <RequestProcessSummary
                item={item}
                matching={matchingQuery.data}
                identity={identityQuery.data}
                identityPending={identityQuery.isPending}
                legalPersona={legalPersona}
              />
            </TabsContent>

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
                  canReviewActions={canReviewActions && !legalPersona}
                  actionPending={actionPending}
                  onPromote={(responseStatus) =>
                    promoteMutation.mutate(responseStatus)
                  }
                  onDecline={() => declineMutation.mutate()}
                  compact
                  layout="tabs"
                  hideActions
                />
                {legalPersona && showAssignmentToLegal ? (
                  <p className="mt-2 text-[0.7rem] text-ink-soft">
                    Matching is read-only here — use Start fulfillment in the next-step card
                    (or request detail Fulfillment tab) after disposition is recorded.
                  </p>
                ) : null}
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

            {showComms && showDelivery ? (
              <TabsContent value="comms" className="mt-0 text-xs text-ink-soft">
                <p className="font-medium text-ink">Requester communications</p>
                <p className="mt-1">
                  Outbound drafts, sent attempts, and inbound replies will thread here. Use
                  the Access delivery email tab (render API) for access URL emails today.
                </p>
              </TabsContent>
            ) : null}

            {isAccessRequest === true ? (
              <TabsContent value="access-email" className="mt-0">
                <AccessDeliveryEmailCard requestId={item.request_id} />
              </TabsContent>
            ) : null}

            <TabsContent value="activity" className="mt-0">
              <InboxActivityPanel
                requestId={item.request_id}
                canCompose={canReviewActions}
              />
            </TabsContent>

            <TabsContent value="comments" className="mt-0 flex min-h-[16rem] flex-col space-y-2">
              <div className="min-h-0 flex-1 space-y-1">
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
              {canReviewActions && legalPersona ? (
                <LegalInboxComposer
                  item={item}
                  canReviewActions={canReviewActions}
                  myEmail={me?.email}
                  onSuccess={async () => {
                    await queryClient.invalidateQueries({
                      queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'comments'],
                    })
                    await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
                  }}
                />
              ) : canReviewActions ? (
                <div className="flex shrink-0 items-end gap-2 border-t border-line pt-2">
                  <textarea
                    className="min-h-[3.5rem] max-h-32 flex-1 resize-y rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
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
            </TabsContent>
          </div>
        </Tabs>
      </div>
  )
}



type InboxStackKind = 'batch' | 'type' | 'batch_type'

type InboxRow =
  | {
      kind: 'thread'
      stackKind: InboxStackKind
      batchKey: string
      batchLabel: string
      items: NeedsAttentionItem[]
    }
  | { kind: 'request'; item: NeedsAttentionItem }

function findThreadRow(
  rows: InboxRow[],
  batchKey: string,
): Extract<InboxRow, { kind: 'thread' }> | null {
  for (const row of rows) {
    if (row.kind === 'thread' && row.batchKey === batchKey) return row
  }
  return null
}

function countThreadStacks(rows: InboxRow[]): number {
  return rows.filter((row) => row.kind === 'thread').length
}

const UNKEYED_BATCH_KEY = 'u:none'
const UNKEYED_BATCH_LABEL = 'No DROP batch'

function itemBatchParts(item: NeedsAttentionItem): { key: string; label: string } {
  const key = inboxBatchKey(item)
  if (key != null) {
    return { key, label: inboxBatchLabel(item) }
  }
  return { key: UNKEYED_BATCH_KEY, label: UNKEYED_BATCH_LABEL }
}

/**
 * Batch × type cross-product: one stack per (batch, work-type) pair.
 * Example: batch #1 × Notice, batch #1 × Delivery, batch #2 × Notice, …
 */
function buildBatchTypeCrossRows(items: NeedsAttentionItem[]): InboxRow[] {
  type CrossGroup = {
    batchKey: string
    batchLabel: string
    typeKey: InboxWorkType
    typeLabel: string
    items: NeedsAttentionItem[]
  }
  const groups = new Map<string, CrossGroup>()

  for (const item of items) {
    const batch = itemBatchParts(item)
    const typeKey = inboxWorkType(item)
    const compositeKey = `${batch.key}::${typeKey}`
    const existing = groups.get(compositeKey)
    if (existing) {
      existing.items.push(item)
    } else {
      groups.set(compositeKey, {
        batchKey: batch.key,
        batchLabel: batch.label,
        typeKey,
        typeLabel: INBOX_WORK_TYPE_LABELS[typeKey],
        items: [item],
      })
    }
  }

  const typeRank = new Map(
    INBOX_WORK_TYPE_ORDER.map((key, index) => [key, index] as const),
  )

  const timed = [...groups.entries()].map(([compositeKey, group]) => {
    const sorted = [...group.items].sort((a, b) =>
      (a.requested_at ?? '').localeCompare(b.requested_at ?? ''),
    )
    return {
      t: sorted[0]?.requested_at ?? '',
      typeRank: typeRank.get(group.typeKey) ?? 99,
      batchLabel: group.batchLabel,
      row: {
        kind: 'thread' as const,
        stackKind: 'batch_type' as const,
        batchKey: compositeKey,
        batchLabel: `${group.batchLabel} · ${group.typeLabel}`,
        items: sorted,
      },
    }
  })

  timed.sort((a, b) => {
    const byTime = a.t.localeCompare(b.t)
    if (byTime !== 0) return byTime
    const byType = a.typeRank - b.typeRank
    if (byType !== 0) return byType
    return a.batchLabel.localeCompare(b.batchLabel)
  })
  return timed.map((entry) => entry.row)
}

/** Stack by batch, by type, or by batch×type when both toggles are on. */
function buildGroupedInboxRows(
  items: NeedsAttentionItem[],
  options: { byBatch: boolean; byType: boolean },
): InboxRow[] {
  if (options.byBatch && options.byType) {
    return buildBatchTypeCrossRows(items)
  }
  if (options.byType) {
    const rows: InboxRow[] = []
    for (const section of buildTypeSections(items)) {
      const sorted = [...section.items].sort((a, b) =>
        (a.requested_at ?? '').localeCompare(b.requested_at ?? ''),
      )
      rows.push({
        kind: 'thread',
        stackKind: 'type',
        batchKey: `type:${section.key}`,
        batchLabel: section.label,
        items: sorted,
      })
    }
    return rows
  }
  return buildInboxRows(items, options.byBatch)
}

function InboxGroupSwitch({
  label,
  checked,
  onToggle,
  ariaLabel,
  titleOn,
  titleOff,
}: {
  label: string
  checked: boolean
  /** Prefer functional toggle — avoids stale `!checked` on rapid clicks. */
  onToggle: () => void
  ariaLabel: string
  titleOn: string
  titleOff: string
}) {
  return (
    <div className="flex shrink-0 items-center gap-1.5 text-[0.65rem] text-ink-soft">
      <span className="uppercase tracking-wide text-mute">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={ariaLabel}
        title={checked ? titleOn : titleOff}
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          onToggle()
        }}
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors',
          checked
            ? 'border-habeas-navy/40 bg-habeas-navy'
            : 'border-line bg-canvas',
        )}
      >
        <span
          className={cn(
            'pointer-events-none block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform duration-150',
            checked ? 'translate-x-[1.125rem]' : 'translate-x-0.5',
          )}
          aria-hidden
        />
      </button>
    </div>
  )
}

/** When grouping is on, never leave bare request rows at the top level. */
function coerceGroupedInboxRows(
  rows: InboxRow[],
  groupingActive: boolean,
): InboxRow[] {
  if (!groupingActive) return rows
  return rows.map((row) => {
    if (row.kind === 'thread') return row
    return {
      kind: 'thread',
      stackKind: 'batch',
      batchKey: `singleton:${row.item.request_id}`,
      batchLabel: inboxItemTitle(row.item),
      items: [row.item],
    }
  })
}

type ActiveTarget =
  | { kind: 'thread'; batchKey: string }
  | { kind: 'request'; requestId: string }

/** Prefer download attempt id; fall back to ZIP member name (seed/broker rows). */
function inboxBatchKey(item: NeedsAttentionItem): string | null {
  if (item.bulk_process_id != null) return `p:${item.bulk_process_id}`
  if (item.source_csv_filename) return `c:${item.source_csv_filename}`
  return null
}

function threadIsExactMatchBatch(items: NeedsAttentionItem[]): boolean {
  return items.length > 0 && items.every((entry) => entry.match_type === 'single_match')
}

function inboxBatchLabel(item: NeedsAttentionItem): string {
  if (item.bulk_process_id != null) return `#${item.bulk_process_id}`
  const name = item.source_csv_filename?.split('/').pop() ?? item.source_csv_filename
  if (!name) return 'batch'
  return name.replace(/\.csv$/i, '')
}

/**
 * When Batch is on: every row is a stack — keyed DROP batches (including size 1)
 * plus one leftover stack for items with no process/CSV key.
 */
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
    timed.push({
      t: sorted[0]?.requested_at ?? '',
      row: {
        kind: 'thread',
        stackKind: 'batch',
        batchKey,
        batchLabel: inboxBatchLabel(sorted[0]!),
        items: sorted,
      },
    })
  }

  if (individuals.length > 0) {
    const sorted = [...individuals].sort((a, b) =>
      (a.requested_at ?? '').localeCompare(b.requested_at ?? ''),
    )
    timed.push({
      t: sorted[0]?.requested_at ?? '',
      row: {
        kind: 'thread',
        stackKind: 'batch',
        batchKey: UNKEYED_BATCH_KEY,
        batchLabel: UNKEYED_BATCH_LABEL,
        items: sorted,
      },
    })
  }

  timed.sort((a, b) => a.t.localeCompare(b.t))
  return timed.map((entry) => entry.row)
}

/** Shared download-attempt id when every member has the same bulk_process_id. */
function sharedBulkProcessId(items: NeedsAttentionItem[]): number | null {
  if (items.length === 0) return null
  const first = items[0]?.bulk_process_id
  if (first == null) return null
  return items.every((item) => item.bulk_process_id === first) ? first : null
}

function batchClusterAsPipelineRows(rows: WorkbenchVerticalBatchRow[]) {
  return rows.map((row) => {
    const countParts = Object.entries(row.member_status_counts)
      .filter(([, n]) => n > 0)
      .map(([status, n]) => `${n} ${status}`)
    return {
      vertical: row.vertical,
      label: row.label,
      live: row.live,
      matching_status: row.matching_status,
      fulfillment_status: row.fulfillment_status,
      blocker: countParts.length > 0 ? countParts.join(', ') : null,
    }
  })
}

function ThreadReviewPane({
  batchLabel,
  items,
  stackKind = 'batch',
  canReviewActions,
  onPromoteAll,
  onDeclineAll,
  actionPending,
  onBackToQueue,
  onOpenDetail,
}: {
  batchLabel: string
  items: NeedsAttentionItem[]
  stackKind?: InboxStackKind
  canReviewActions: boolean
  onPromoteAll: (responseStatus: DropResponseStatusCode) => void
  onDeclineAll: () => void
  actionPending: boolean
  onBackToQueue?: () => void
  onOpenDetail?: (item: NeedsAttentionItem, trigger: HTMLElement) => void
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
  const exactMatchBatch =
    (stackKind === 'batch' || stackKind === 'batch_type') &&
    threadIsExactMatchBatch(items)
  const showBulkMatchingActions = canReviewActions && exactMatchBatch
  const groupNoun =
    stackKind === 'type' ? 'Type' : stackKind === 'batch_type' ? 'Batch · type' : 'Batch'

  const bulkId =
    stackKind === 'batch' || stackKind === 'batch_type'
      ? sharedBulkProcessId(items)
      : null

  const batchWorkbenchQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'batches', bulkId, 'journey-workbench'],
    queryFn: async () => {
      try {
        return await getBatchJourneyWorkbench(bulkId!)
      } catch (error) {
        // Soft-fail missing workbench (same as InboxReviewPane individual path).
        if (error instanceof Error && /Admin API 404/.test(error.message)) {
          return null
        }
        throw error
      }
    },
    enabled: bulkId != null,
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
    retry: false,
  })

  // No shared bulk_process_id (type stacks / unkeyed CSV stacks): do NOT invent a
  // fake batch aggregate. Derive four-stage chrome from the first member's ops
  // journey only — member list remains the source of truth for the group.
  const firstMember = items[0] ?? null
  const fallbackJourneyQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      firstMember?.request_id,
      'journey',
      'thread-fallback',
    ],
    queryFn: () => getRequestJourney(firstMember!.request_id),
    enabled: bulkId == null && firstMember != null,
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const derivedChrome = fallbackJourneyQuery.data
    ? deriveWorkbenchChromeFromOpsJourney({
        stages: fallbackJourneyQuery.data.stages,
        current_stage: fallbackJourneyQuery.data.current_stage,
        intake_source: firstMember!.intake_source,
        request_type: null,
      })
    : null

  const batchWorkbench = batchWorkbenchQuery.data
  const pipelineStages = batchWorkbench?.stages ?? derivedChrome?.stages ?? []
  const pipelineSubsteps =
    bulkId != null
      ? undefined
      : derivedChrome?.substeps
  const matchingCluster = batchWorkbench
    ? batchClusterAsPipelineRows(batchWorkbench.matching_cluster)
    : undefined
  const fulfillmentCluster = batchWorkbench
    ? batchClusterAsPipelineRows(batchWorkbench.fulfillment_cluster)
    : undefined

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
        <Micro>
          {stackKind === 'type'
            ? 'Type stack'
            : stackKind === 'batch_type'
              ? 'Batch · type stack'
              : 'Batch thread'}
        </Micro>
        <h2 className="text-sm font-medium text-ink">
          {exactMatchBatch
            ? `Exact 1:1 matches · ${items.length} requests`
            : `${groupNoun} stack · ${items.length} requests`}
        </h2>
        <dl className="flex flex-wrap gap-x-4 gap-y-1 text-[0.7rem] text-ink-soft">
          <div>
            Group{' '}
            <span
              className={
                stackKind === 'type' || stackKind === 'batch_type'
                  ? 'text-ink'
                  : 'font-mono text-ink'
              }
            >
              {batchLabel}
            </span>
          </div>
          {exactMatchBatch ? (
            <div>
              Match <span className="text-ink">single match</span>
            </div>
          ) : null}
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

      {/* Same four-stage chrome as individual Inbox detail (KD2) — batch aggregate when keyed. */}
      {pipelineStages.length > 0 ? (
        <div className="shrink-0 border-b border-line px-4 py-2">
          <ThinJourneyPipeline
            stages={pipelineStages}
            substeps={pipelineSubsteps}
            matchingCluster={matchingCluster}
            fulfillmentCluster={fulfillmentCluster}
            splitPosture={
              batchWorkbench?.split_posture ?? derivedChrome?.split_posture
            }
            density="compact"
          />
          {bulkId == null && derivedChrome ? (
            <p className="mt-1 text-center text-[0.55rem] text-mute">
              Journey shown for first member — not a batch aggregate
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        <p className="text-xs text-ink-soft">
          {exactMatchBatch ? (
            <>
              These requests each matched exactly one DWID in DROP batch{' '}
              <span className="font-mono">{batchLabel}</span>. Fulfill the whole thread at
              once, or open a single request below.
            </>
          ) : stackKind === 'type' ? (
            <>
              These requests share work type <span className="text-ink">{batchLabel}</span>.
              Open a member below for full detail.
            </>
          ) : stackKind === 'batch_type' ? (
            <>
              These requests share batch and work type{' '}
              <span className="text-ink">{batchLabel}</span>. Open a member below for full
              detail.
            </>
          ) : (
            <>
              These requests share DROP batch{' '}
              <span className="font-mono">{batchLabel}</span>. Open a member below for full
              detail.
            </>
          )}
        </p>
        <ul className="max-h-56 divide-y divide-line overflow-y-auto rounded-lg border border-line">
          {items.map((entry) => (
            <li key={entry.request_id} className="text-[0.7rem]">
              {onOpenDetail ? (
                <button
                  type="button"
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-canvas"
                  onClick={(event) => onOpenDetail(entry, event.currentTarget)}
                >
                  <span className="font-mono text-ink">
                    {entry.request_id.slice(0, 8)}…
                  </span>
                  <span className="text-mute">
                    {entry.requestor_state ?? '—'}
                    {entry.match_type ? ` · ${matchTypeLabel(entry.match_type)}` : ''}
                    {entry.matched_via ? ` · ${entry.matched_via}` : ''}
                  </span>
                </button>
              ) : (
                <div className="flex items-center justify-between gap-2 px-3 py-2">
                  <span className="font-mono text-ink">
                    {entry.request_id.slice(0, 8)}…
                  </span>
                  <span className="text-mute">
                    {entry.requestor_state ?? '—'}
                    {entry.match_type ? ` · ${matchTypeLabel(entry.match_type)}` : ''}
                    {entry.matched_via ? ` · ${entry.matched_via}` : ''}
                  </span>
                </div>
              )}
            </li>
          ))}
        </ul>
        {showBulkMatchingActions ? (
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
      </div>
    </div>
  )
}


export function NeedsAttentionPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const search = useSearch({ from: '/requests/needs-attention' })
  const bulkFilter = search.bulk
  const { isAdmin, role, me, isLoading: meLoading } = useMe()
  const legalPersona = isLegalAdminPersona(role)
  const dataOwnerPersona = role === 'data_owner'
  const canReviewActions =
    Boolean(isAdmin) || legalPersona || dataOwnerPersona
  const inboxTabs = dataOwnerPersona
    ? DATA_OWNER_INBOX_KIND_TABS
    : OPS_INBOX_KIND_TABS
  const defaultKind: InboxKind = legalPersona
    ? 'triage'
    : dataOwnerPersona || bulkFilter != null
      ? 'matching'
      : 'all'
  /** null = no filter chip (show full Legal inbox). URL omits `filter`. */
  const [legalInboxFilter, setLegalInboxFilter] = useState<LegalInboxFilter | null>(
    () => search.filter ?? null,
  )
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [activeTarget, setActiveTarget] = useState<ActiveTarget | null>(null)
  const [expandedThreads, setExpandedThreads] = useState<Set<string>>(new Set())
  const [inboxKind, setInboxKind] = useState<InboxKind>(
    () => (search.kind as InboxKind | undefined) ?? defaultKind,
  )
  const [matchFilter, setMatchFilter] = useState<MatchFilter>('all')
  const [dueFilter, setDueFilter] = useState<DueFilter>('all')
  /** null → persona default (legal: off, ops/matching: on). */
  const [groupByBatchOverride, setGroupByBatchOverride] = useState<boolean | null>(
    null,
  )
  const groupByBatch = groupByBatchOverride ?? !legalPersona
  const [groupByType, setGroupByType] = useState(false)
  const groupingActive = groupByBatch || groupByType
  const [page, setPage] = useState(1)

  useEffect(() => {
    // Collapsed stacks when grouping mode changes — avoids “stuck” expanded flat-looking lists.
    setExpandedThreads(new Set())
  }, [groupByBatch, groupByType])

  useEffect(() => {
    if (legalPersona) {
      setLegalInboxFilter(search.filter ?? null)
    }
    if (search.assignee) {
      setInboxKind('matching')
      return
    }
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
  }, [bulkFilter, dataOwnerPersona, legalPersona, search.assignee, search.filter, search.kind])

  const [bulkAssignee, setBulkAssignee] = useState('')
  const [bulkAssignTarget, setBulkAssignTarget] = useState<AssignTarget | null>(null)
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
  const detailOverlay = useRequestDetailOverlay()

  // Server-paginated as a growing prefix window: fetching offset=0 with a limit that
  // scales with `page` means "Next" always triggers a real API refetch (queryKey
  // includes page) while `items` still holds every row loaded so far — so tab
  // counts, batch/type grouping, and "select all" keep working the way they always
  // have (now meaning "all rows loaded", not the whole inbox). Capped at the same
  // 1000-row admin-api safety limit as before, but most sessions never page that far.
  const inboxFetchLimit = Math.min(1000, page * INBOX_PAGE_SIZE)

  const attentionQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      'needs-attention',
      legalPersona ? 'legal' : dataOwnerPersona ? 'data-owner' : 'ops',
      search.assignee ?? null,
      inboxFetchLimit,
    ],
    queryFn: () => {
      if (search.assignee) {
        return getNeedsAttention({
          limit: inboxFetchLimit,
          offset: 0,
          kind: 'matching',
          assignee: search.assignee,
        })
      }
      return legalPersona
        ? getLegalNeedsAttention({ limit: inboxFetchLimit, offset: 0 })
        : dataOwnerPersona
          ? getNeedsAttention({ limit: inboxFetchLimit, offset: 0, kind: 'matching' })
          : getNeedsAttention({ limit: inboxFetchLimit, offset: 0 })
    },
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  function setLegalFilterAndUrl(next: LegalInboxFilter | null) {
    setLegalInboxFilter(next)
    setMobilePane('queue')
    void navigate({
      to: '/requests/needs-attention',
      // Build a full search object (omit cleared keys) so filters can toggle off.
      search: (prev) => {
        const nextSearch: {
          bulk?: number
          filter?: LegalInboxFilter
          assignee?: string
        } = {}
        if (prev.bulk != null) nextSearch.bulk = prev.bulk
        if (prev.assignee) nextSearch.assignee = prev.assignee
        if (next != null) nextSearch.filter = next
        return nextSearch
      },
      replace: true,
    })
  }

  function setInboxKindAndUrl(next: InboxKind) {
    setInboxKind(next)
    setMobilePane('queue')
    if (next !== 'matching' && next !== 'all') {
      setMatchFilter('all')
    }
    void navigate({
      to: '/requests/needs-attention',
      search: (prev) => {
        const nextSearch: {
          bulk?: number
          kind?: InboxKind
          assignee?: string
          filter?: LegalInboxFilter
        } = {}
        if (prev.bulk != null) nextSearch.bulk = prev.bulk
        if (prev.assignee) nextSearch.assignee = prev.assignee
        if (prev.filter) nextSearch.filter = prev.filter
        if (!(next === defaultKind && !legalPersona)) nextSearch.kind = next
        return nextSearch
      },
      replace: true,
    })
  }

  const items = attentionQuery.data?.items ?? []

  const operatorsQuery = useQuery({
    queryKey: ['admin-api', 'legal', 'operators'],
    queryFn: getLegalOperators,
    enabled: Boolean(isAdmin || legalPersona),
    staleTime: 60_000,
  })

  const assigneeCandidates = useMemo(() => {
    const set = new Set<string>()
    if (me?.email) set.add(me.email)
    for (const item of items) {
      const email = item.assignment?.assignee_identity?.trim()
      if (email) set.add(email)
    }
    for (const operator of operatorsQuery.data ?? []) {
      const email = operator.email?.trim()
      if (email) set.add(email)
    }
    return [...set].sort((a, b) => a.localeCompare(b))
  }, [items, me?.email, operatorsQuery.data])

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

  const showMatchResultFilters =
    matchOptions.length > 0 &&
    (legalPersona
      ? legalInboxFilter == null ||
        legalInboxFilter === 'fulfillment' ||
        legalInboxFilter === 'assignment_to_legal' ||
        legalInboxFilter === 'notice' ||
        legalInboxFilter === 'unassigned'
      : inboxKind === 'matching' || inboxKind === 'all')

  const filteredItems = useMemo(() => {
    const myEmail = me?.email
    return items.filter((item) => {
      if (bulkFilter != null && item.bulk_process_id !== bulkFilter) return false
      if (legalPersona) {
        if (
          legalInboxFilter != null &&
          !matchesLegalInboxFilter(item, legalInboxFilter, myEmail)
        ) {
          return false
        }
        if (matchFilter !== 'all' && showMatchResultFilters) {
          const key = (item.match_type as MatchFilter | undefined) ?? 'unknown'
          if (key !== matchFilter) return false
        }
      } else {
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
      }
      if (dueFilter !== 'all' && dueBucket(item) !== dueFilter) return false
      return true
    })
  }, [
    items,
    inboxKind,
    legalInboxFilter,
    legalPersona,
    matchFilter,
    dueFilter,
    me?.email,
    bulkFilter,
    showMatchResultFilters,
  ])

  const inboxRows = useMemo(
    () =>
      coerceGroupedInboxRows(
        buildGroupedInboxRows(filteredItems, {
          byBatch: groupByBatch,
          byType: groupByType,
        }),
        groupingActive,
      ),
    [filteredItems, groupByBatch, groupByType, groupingActive],
  )

  const stackCount = useMemo(() => countThreadStacks(inboxRows), [inboxRows])

  // Reset to page 1 whenever the filter/grouping/search context changes — otherwise a stale
  // page number can land the user on an empty page after the list reshapes.
  useEffect(() => {
    setPage(1)
  }, [
    legalInboxFilter,
    inboxKind,
    matchFilter,
    dueFilter,
    groupByBatch,
    groupByType,
    bulkFilter,
    search.assignee,
  ])

  const {
    items: pagedInboxRows,
    totalPages: inboxLocalTotalPages,
    currentPage: inboxCurrentPage,
    start: inboxPageStart,
    end: inboxPageEnd,
    total: inboxPageTotal,
  } = paginate(inboxRows, page, INBOX_PAGE_SIZE)

  // items.length can lag behind the server's real total while a bigger page's worth of
  // rows is still loading (growing prefix window) — keep "Next" enabled in that case so
  // paging forward triggers the fetch instead of looking like a dead end.
  const rawInboxTotal = attentionQuery.data?.total ?? items.length
  const moreRowsToLoad = items.length < Math.min(rawInboxTotal, 1000)
  const inboxTotalPages = moreRowsToLoad
    ? Math.max(inboxLocalTotalPages, inboxCurrentPage + 1)
    : inboxLocalTotalPages

  useEffect(() => {
    if (inboxRows.length === 0) {
      setActiveTarget(null)
      return
    }
    const stillValid =
      activeTarget != null &&
      (activeTarget.kind === 'thread'
        ? findThreadRow(inboxRows, activeTarget.batchKey) != null
        : filteredItems.some((item) => item.request_id === activeTarget.requestId))
    if (!stillValid) {
      const first =
        inboxRows.find((row) => row.kind === 'thread' || row.kind === 'request') ??
        null
      if (!first) {
        setActiveTarget(null)
        return
      }
      setActiveTarget(
        first.kind === 'thread'
          ? { kind: 'thread', batchKey: first.batchKey }
          : { kind: 'request', requestId: first.item.request_id },
      )
    }
  }, [inboxRows, filteredItems, activeTarget])

  const activeThread =
    activeTarget?.kind === 'thread'
      ? findThreadRow(inboxRows, activeTarget.batchKey)
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
      return { succeeded, failed, action }
    },
    onSuccess: async (result, variables) => {
      const verb = result.action === 'fulfill' ? 'fulfilled' : 'declined'
      if (result.failed > 0) {
        actionToast.warning({
          title:
            result.action === 'fulfill'
              ? 'Bulk fulfill partially completed'
              : 'Bulk decline partially completed',
          description: `${result.succeeded} ${verb}, ${result.failed} failed`,
          action: {
            label: 'Retry',
            onClick: () => bulkMutation.mutate(variables),
          },
        })
      } else {
        actionToast.success({
          title:
            result.action === 'fulfill' ? 'Requests fulfilled' : 'Requests declined',
          description: `${result.succeeded} ${verb}`,
        })
      }
      setSelectedIds(new Set())
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Bulk action failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => bulkMutation.mutate(variables),
        },
      })
      setBulkConfirm(null)
    },
  })

  const bulkAssignMutation = useMutation({
    mutationFn: async ({
      requestIds,
      target,
    }: {
      requestIds: string[]
      target: AssignTarget
    }) => {
      if (target.kind === 'group') {
        return postDropWorkflowEscalate({
          request_ids: requestIds,
          target_role: target.group === 'legal' ? 'legal' : 'data_owner',
        })
      }
      return postDropWorkflowAssign({
        request_ids: requestIds,
        assignee_identity: target.email,
        target_role: 'reviewer',
      })
    },
    onSuccess: async (_result, variables) => {
      actionToast.success({
        title: 'Requests assigned',
        description: `${variables.requestIds.length} updated`,
      })
      setBulkAssignee('')
      setBulkAssignTarget(null)
      setSelectedIds(new Set())
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Bulk assign failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => bulkAssignMutation.mutate(variables),
        },
      })
      setBulkConfirm(null)
    },
  })

  const bulkTriageRejectMutation = useMutation({
    mutationFn: (requestIds: string[]) =>
      postTriageBulkReject({ request_ids: requestIds, response_status: 2 }),
    onSuccess: async (result) => {
      if (result.count === 0) {
        actionToast.warning({
          title: 'No rows rejected',
          description: 'None of the selected items were in triage.',
        })
      } else {
        actionToast.success({
          title: 'Rejected as exempted',
          description: `${result.count} updated`,
        })
      }
      setSelectedIds(new Set())
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Bulk reject failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => bulkTriageRejectMutation.mutate(variables),
        },
      })
      setBulkConfirm(null)
    },
  })

  const bulkTriageMatchMutation = useMutation({
    mutationFn: (requestIds: string[]) =>
      postTriageSendToMatching({ request_ids: requestIds }),
    onSuccess: async (result) => {
      actionToast.success({
        title: 'Sent to matching',
        description: `${result.count} updated`,
      })
      setSelectedIds(new Set())
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Send to matching failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => bulkTriageMatchMutation.mutate(variables),
        },
      })
      setBulkConfirm(null)
    },
  })

  const bulkNoticeApproveMutation = useMutation({
    mutationFn: (requestIds: string[]) =>
      postNoticeApprove({ request_ids: requestIds }),
    onSuccess: async (result) => {
      if (result.count === 0) {
        actionToast.warning({
          title: 'No rows approved',
          description: 'None of the selected items were pending notice approval.',
        })
      } else {
        actionToast.success({
          title: NOTICE_APPROVAL.action,
          description: `${result.count} updated`,
        })
      }
      setSelectedIds(new Set())
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Notice approve failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => bulkNoticeApproveMutation.mutate(variables),
        },
      })
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
    // Select-all acts on every row loaded so far (server-paginated growing window),
    // not the whole server-side total — see the "(of N)" hint in the selection chip.
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
        description={
          bulkAssignTarget?.kind === 'group'
            ? `Send selected reviews to the ${
                bulkAssignTarget.group === 'legal' ? 'Legal' : 'Data'
              } team queue.`
            : `Assign selected reviews to ${
                bulkAssignTarget?.kind === 'user'
                  ? bulkAssignTarget.email
                  : bulkAssignee.trim() || 'the reviewer'
              }.`
        }
        confirmLabel="Assign selected"
        confirming={bulkAssignMutation.isPending}
        onConfirm={() => {
          const target: AssignTarget | null =
            bulkAssignTarget ??
            (bulkAssignee.trim()
              ? { kind: 'user', email: bulkAssignee.trim() }
              : null)
          if (!target) return
          bulkAssignMutation.mutate({
            requestIds: allFilteredSelected ? [...filteredIds] : [...selectedIds],
            target,
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
        title={`${NOTICE_APPROVAL.action} for ${allFilteredSelected ? filteredIds.length : selectedCount}?`}
        description={NOTICE_APPROVAL.hint}
        confirmLabel={NOTICE_APPROVAL.action}
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
              ? 'Open work for legal — filter, act, move on.'
              : dataOwnerPersona
                ? 'Matching review and tasks assigned to you.'
                : 'Pending matching, delivery, notice, and communications.'}
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

      <div className="taste-panel flex min-h-0 flex-1 flex-col overflow-hidden">
        <div
          className={cn(
            'min-w-0 shrink-0 items-center gap-1 overflow-x-auto border-b border-line px-2.5 py-1.5',
            mobilePane === 'detail' ? 'hidden md:flex' : 'flex',
          )}
          role="toolbar"
          aria-label="Inbox filters"
        >
          {legalPersona ? (
            <>
              {LEGAL_INBOX_PRIMARY_FILTERS.map((chip) => {
                const count = items.filter((item) =>
                  matchesLegalInboxFilter(item, chip.value, me?.email),
                ).length
                return (
                  <FilterChip
                    key={chip.value}
                    compact
                    active={legalInboxFilter === chip.value}
                    label={chip.shortLabel}
                    title={chip.label}
                    count={count}
                    onClick={() =>
                      setLegalFilterAndUrl(
                        legalInboxFilter === chip.value ? null : chip.value,
                      )
                    }
                  />
                )
              })}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    className={cn(
                      'inline-flex h-7 shrink-0 items-center gap-1 rounded-md border px-2 text-[0.65rem] font-medium transition-colors',
                      LEGAL_INBOX_MORE_FILTERS.some(
                        (chip) => chip.value === legalInboxFilter,
                      )
                        ? 'border-habeas-navy bg-habeas-navy text-white'
                        : 'border-line bg-paper text-ink-soft hover:border-ink/30 hover:text-ink',
                    )}
                    aria-label="More inbox filters"
                  >
                    {LEGAL_INBOX_MORE_FILTERS.find(
                      (chip) => chip.value === legalInboxFilter,
                    )?.shortLabel ?? 'More'}
                    <span aria-hidden className="text-[0.55rem] opacity-80">
                      ▾
                    </span>
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-52">
                  <DropdownMenuLabel>Filters</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {LEGAL_INBOX_MORE_FILTERS.map((chip) => {
                    const selected = legalInboxFilter === chip.value
                    const count = items.filter((item) =>
                      matchesLegalInboxFilter(item, chip.value, me?.email),
                    ).length
                    return (
                      <DropdownMenuItem
                        key={chip.value}
                        className="justify-between gap-3"
                        onSelect={(event) => {
                          event.preventDefault()
                          setLegalFilterAndUrl(selected ? null : chip.value)
                        }}
                      >
                        <span className="flex items-center gap-2">
                          <span
                            className={cn(
                              'flex h-3.5 w-3.5 items-center justify-center rounded border text-[0.55rem]',
                              selected
                                ? 'border-habeas-navy bg-habeas-navy text-white'
                                : 'border-line text-transparent',
                            )}
                            aria-hidden
                          >
                            ✓
                          </span>
                          {chip.label}
                        </span>
                        <span className="tabular-nums text-mute">{count}</span>
                      </DropdownMenuItem>
                    )
                  })}
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          ) : (
            <Tabs
              value={inboxKind}
              onValueChange={(value) => setInboxKindAndUrl(value as InboxKind)}
              className="min-w-0 shrink-0"
            >
              <TabsList className="h-7 w-auto justify-start gap-0.5 bg-canvas p-0.5">
                {inboxTabs.map((tab) => (
                  <TabsTrigger
                    key={tab.value}
                    value={tab.value}
                    className="h-6 shrink-0 gap-1 px-1.5 text-[0.65rem]"
                  >
                    {tab.label}
                    <span className="tabular-nums opacity-70">{kindCounts[tab.value]}</span>
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          )}

          <span
            className="mx-1.5 h-6 w-px shrink-0 self-center bg-line"
            aria-hidden
          />
          <div
            className="flex shrink-0 items-center gap-2 rounded-md border border-line/80 bg-canvas/70 px-2 py-0.5"
            role="group"
            aria-label="List grouping"
          >
            <span className="shrink-0 text-[0.6rem] uppercase tracking-wide text-mute">
              Group
            </span>
            <InboxGroupSwitch
              label="Batch"
              checked={groupByBatch}
              onToggle={() =>
                setGroupByBatchOverride((previous) => !(previous ?? !legalPersona))
              }
              ariaLabel="Group inbox by DROP batch"
              titleOn="Batch grouping on — click to show flat rows"
              titleOff="Batch grouping off — click to stack by DROP batch"
            />
            <InboxGroupSwitch
              label="Type"
              checked={groupByType}
              onToggle={() => setGroupByType((previous) => !previous)}
              ariaLabel="Group inbox by work type"
              titleOn="Type grouping on — click to show flat type rows"
              titleOff="Type grouping off — click to stack by work type"
            />
          </div>
          {showMatchResultFilters ? (
            <>
              <span className="ml-0.5 shrink-0 text-[0.6rem] uppercase tracking-wide text-mute">
                Result
              </span>
              <FilterChip
                compact
                active={matchFilter === 'all'}
                label="All"
                title="All results"
                onClick={() => setMatchFilter('all')}
              />
              {matchOptions.map(([matchType, count]) => (
                <FilterChip
                  key={matchType}
                  compact
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
              <span className="ml-0.5 shrink-0 text-[0.6rem] uppercase tracking-wide text-mute">
                Due
              </span>
              {dueOptions.map(([due, count]) => (
                <FilterChip
                  key={due}
                  compact
                  active={dueFilter === due}
                  label={
                    due === 'overdue'
                      ? 'Overdue'
                      : due === 'due_soon'
                        ? 'Soon'
                        : 'On track'
                  }
                  title={
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

        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]">
        <div
          className={cn(
            'min-h-0 flex-col border-line md:border-r',
            mobilePane === 'detail' ? 'hidden md:flex' : 'flex',
          )}
        >
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

            {legalPersona && legalInboxFilter === 'pre_matching_holds' ? (
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

            {legalPersona && legalInboxFilter === 'notice' ? (
              <Button
                size="sm"
                disabled={selectedCount === 0 || noticeBulkPending}
                onClick={() => setBulkConfirm('notice_approve')}
              >
                {bulkNoticeApproveMutation.isPending
                  ? 'Approving…'
                  : NOTICE_APPROVAL.action}
              </Button>
            ) : null}

            <div className="ml-auto flex items-center gap-2">
              {selectedCount > 0 ? (
                <span className="taste-frost-chip tabular-nums text-[0.65rem]">
                  {allFilteredSelected
                    ? `All ${filteredIds.length} loaded${moreRowsToLoad ? ` (of ${rawInboxTotal})` : ''}`
                    : `${selectedInFilterCount} of ${filteredIds.length} loaded`}
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
                  #{filteredItems.length} loaded
                  {moreRowsToLoad ? ` (of ${rawInboxTotal} — page forward to load more)` : ''}
                  {groupingActive && stackCount > 0
                    ? groupByBatch && groupByType
                      ? ` · ${stackCount} batch×type stacks`
                      : groupByBatch
                        ? ` · ${stackCount} batch stacks`
                        : ` · ${stackCount} type stacks`
                    : ''}
                </span>
              )}
            </div>
          </div>

          {(isAdmin || legalPersona) && selectedCount > 0 ? (
            <div className="flex flex-wrap items-end gap-2 border-b border-line px-3 py-2">
              <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-[0.65rem] text-ink-soft">
                Assign selected
                <input
                  className="rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
                  value={bulkAssignee}
                  onChange={(event) => {
                    setBulkAssignee(event.target.value)
                    setBulkAssignTarget(null)
                  }}
                  list="inbox-assignee-candidates"
                  placeholder="Search people…"
                  aria-label="Bulk assignee email"
                />
                <datalist id="inbox-assignee-candidates">
                  {assigneeCandidates.map((email) => (
                    <option key={email} value={email} />
                  ))}
                </datalist>
              </label>
              <Button
                size="sm"
                variant="outline"
                disabled={
                  bulkAssignMutation.isPending || bulkAssignee.trim().length === 0
                }
                onClick={() => {
                  setBulkAssignTarget({ kind: 'user', email: bulkAssignee.trim() })
                  setBulkConfirm('assign')
                }}
              >
                {bulkAssignMutation.isPending ? 'Assigning…' : 'Assign'}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={bulkAssignMutation.isPending}
                onClick={() => {
                  setBulkAssignTarget({ kind: 'group', group: 'legal' })
                  setBulkConfirm('assign')
                }}
              >
                Legal team
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={bulkAssignMutation.isPending}
                onClick={() => {
                  setBulkAssignTarget({ kind: 'group', group: 'data' })
                  setBulkConfirm('assign')
                }}
              >
                Data team
              </Button>
            </div>
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
                {legalPersona
                  ? legalFilterEmptyMessage(legalInboxFilter)
                  : items.length === 0
                    ? 'Nothing needs attention right now.'
                    : inboxKind === 'triage'
                      ? 'No Legal Triage holds — condition hits land here before matching.'
                      : inboxKind === 'escalations'
                        ? 'No assignment-to-legal items right now.'
                        : inboxKind === 'delivery'
                          ? 'No access delivery tasks in this filter.'
                          : inboxKind === 'notice'
                            ? NOTICE_APPROVAL.empty
                            : inboxKind === 'communications'
                              ? 'No requester comms yet — drafts and replies will land here.'
                              : inboxKind === 'pending_tasks'
                                ? 'No pending tasks assigned to you.'
                                : 'No items match the current view.'}
              </p>
            ) : null}

            {!loading && !attentionQuery.isError && filteredItems.length > 0 ? (
              <ul
                key={`inbox-group-${groupByBatch ? 'b' : ''}${groupByType ? 't' : ''}-n`}
                className={cn(
                  groupingActive ? 'space-y-1 bg-canvas/40 p-1.5' : 'divide-y divide-line',
                )}
              >
                {pagedInboxRows.map((row) => {
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
                    const exactMatchBatch =
                      (row.stackKind === 'batch' || row.stackKind === 'batch_type') &&
                      threadIsExactMatchBatch(row.items)
                    const isTypeStack = row.stackKind === 'type'
                    const isCrossStack = row.stackKind === 'batch_type'
                    const stackKindLabel = isCrossStack
                      ? 'batch·type'
                      : isTypeStack
                        ? 'type'
                        : 'batch'
                    const unbatched =
                      row.batchKey === UNKEYED_BATCH_KEY ||
                      row.batchKey.startsWith(`${UNKEYED_BATCH_KEY}::`)
                    return (
                      <li key={`thread-${row.batchKey}`} className="list-none">
                        <div
                          className={cn(
                            'relative flex items-stretch gap-0 rounded-md border-2 bg-paper shadow-[0_1px_0_rgba(15,35,70,0.06),0_3px_0_-1px_rgba(15,35,70,0.05),0_6px_0_-2px_rgba(15,35,70,0.04)] transition-colors',
                            isCrossStack
                              ? 'border-habeas-navy/45'
                              : isTypeStack
                                ? 'border-habeas-navy/30'
                                : 'border-habeas-navy/40',
                            active
                              ? 'border-habeas-navy/60 bg-habeas-navy/[0.07]'
                              : selected
                                ? 'bg-habeas-navy/[0.03]'
                                : 'hover:border-habeas-navy/50 hover:bg-panel/40',
                          )}
                        >
                          <span
                            className={cn(
                              'w-1 shrink-0 rounded-l-md',
                              isCrossStack
                                ? 'bg-habeas-navy/80'
                                : isTypeStack
                                  ? 'bg-habeas-navy/45'
                                  : 'bg-habeas-navy/70',
                            )}
                            aria-hidden
                          />
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
                              aria-label={`Select ${stackKindLabel} stack ${row.batchLabel}`}
                            />
                          </label>
                          <button
                            type="button"
                            className="mt-1 shrink-0 self-start rounded px-1 py-2.5 text-[0.65rem] text-mute hover:bg-panel hover:text-ink"
                            aria-label={
                              expanded
                                ? `Collapse ${stackKindLabel} stack ${row.batchLabel}`
                                : `Expand ${stackKindLabel} stack ${row.batchLabel}`
                            }
                            onClick={() => toggleThreadExpand(row.batchKey)}
                          >
                            {expanded ? '▾' : '▸'}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              toggleThreadExpand(row.batchKey)
                              setActiveTarget({
                                kind: 'thread',
                                batchKey: row.batchKey,
                              })
                              setMobilePane('detail')
                            }}
                            className="flex min-w-0 flex-1 items-start gap-2.5 px-1 py-3 pr-2 text-left"
                            aria-label={`${stackKindLabel} stack ${row.batchLabel}, ${row.items.length} requests`}
                          >
                            <span
                              className="relative mt-0.5 flex h-7 w-8 shrink-0 items-center justify-center"
                              aria-hidden
                              title="Grouped inbox stack"
                            >
                              <span className="absolute left-0 top-1 h-5 w-5 rounded-md border border-habeas-navy/20 bg-habeas-navy/[0.04]" />
                              <span className="absolute left-1 top-0.5 h-5 w-5 rounded-md border border-habeas-navy/30 bg-habeas-navy/[0.08]" />
                              <span className="relative flex h-5 w-5 items-center justify-center rounded-md border border-habeas-navy/55 bg-paper text-[0.55rem] font-semibold tabular-nums text-habeas-navy shadow-sm">
                                {row.items.length > 99 ? '99+' : row.items.length}
                              </span>
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                                <span
                                  className={cn(
                                    'text-[0.75rem] font-semibold text-ink',
                                    isTypeStack || isCrossStack ? null : 'font-mono',
                                  )}
                                >
                                  {row.batchLabel}
                                </span>
                                <span className="text-[0.7rem] text-mute">
                                  {exactMatchBatch ? 'Exact 1:1 · ' : ''}
                                  {row.items.length} requests
                                </span>
                              </div>
                              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                                {exactMatchBatch ? (
                                  <Badge
                                    variant="ok"
                                    className="normal-case tracking-normal"
                                  >
                                    single match
                                  </Badge>
                                ) : unbatched ? (
                                  <Badge
                                    variant="default"
                                    className="normal-case tracking-normal"
                                  >
                                    unbatched
                                  </Badge>
                                ) : null}
                                <DuePill item={earliest} className="text-[0.6rem]" />
                              </div>
                            </div>
                          </button>
                        </div>
                        {expanded ? (
                          <ul className="mx-1.5 mb-1.5 space-y-0 overflow-hidden rounded-md border border-habeas-navy/15 border-t-0 bg-canvas/50 py-1">
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
                                      <span className="truncate text-[0.7rem] font-medium text-ink">
                                        {inboxItemTitle(item)}
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

                  // Grouping coerce should eliminate this branch; keep as flat fallback only.
                  if (groupingActive) return null

                  const item = row.item
                  const selected = selectedIds.has(item.request_id)
                  const active =
                    activeTarget?.kind === 'request' &&
                    activeTarget.requestId === item.request_id
                  const assignee = item.assignment?.assignee_identity
                  const showRowAssignee = showInboxIndividualAssignee(
                    item,
                    legalPersona,
                  )
                  const urgentAssignment = legalPersona && isAssignmentToLegalItem(item)
                  return (
                    <li key={item.request_id}>
                      <div
                        className={cn(
                          'flex items-stretch gap-0 transition-colors',
                          urgentAssignment && 'border-l-2 border-l-red-600',
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
                          className="flex min-w-0 flex-1 flex-col gap-1 px-1 py-2.5 pr-3 text-left text-xs"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="min-w-0 truncate font-medium text-ink">
                              {inboxItemTitle(item)}
                            </span>
                            <div className="flex shrink-0 items-center gap-1.5">
                              {urgentAssignment ? (
                                <Badge
                                  variant="fail"
                                  className="normal-case tracking-normal text-[0.55rem]"
                                >
                                  Urgent
                                </Badge>
                              ) : null}
                              <DuePill item={item} className="text-[0.6rem]" />
                            </div>
                          </div>
                          <div className="flex flex-wrap items-center gap-1.5 text-[0.65rem] text-ink-soft">
                            <ChannelOriginAvatar item={item} />
                            <span className="text-mute">
                              {SOURCE_LABELS[item.intake_source] ?? item.intake_source}
                            </span>
                            {showRowAssignee ? (
                              assignee ? (
                                <>
                                  <span className="text-mute">·</span>
                                  <span className="max-w-[9rem] truncate">
                                    {assignee.split('@')[0]}
                                  </span>
                                </>
                              ) : (
                                <>
                                  <span className="text-mute">·</span>
                                  <span className="text-mute">Unassigned</span>
                                </>
                              )
                            ) : null}
                          </div>
                        </button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            ) : null}
          </div>

          {!loading && !attentionQuery.isError && filteredItems.length > 0 ? (
            <InboxPaginationBar
              start={inboxPageStart}
              end={inboxPageEnd}
              total={inboxPageTotal}
              currentPage={inboxCurrentPage}
              totalPages={inboxTotalPages}
              onPrev={() => setPage(Math.max(1, inboxCurrentPage - 1))}
              onNext={() => setPage(Math.min(inboxTotalPages, inboxCurrentPage + 1))}
            />
          ) : null}
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
              stackKind={activeThread.stackKind}
              canReviewActions={canReviewActions}
              actionPending={bulkMutation.isPending}
              onBackToQueue={() => setMobilePane('queue')}
              onOpenDetail={(item, trigger) => {
                detailOverlay.openOverlay(
                  item.request_id,
                  trigger,
                  inboxItemToSeedRequest(item),
                )
              }}
              onPromoteAll={(responseStatus) => {
                bulkMutation.mutate({
                  action: 'fulfill',
                  requestIds: activeThread.items.map((item) => item.request_id),
                  responseStatus,
                })
              }}
              onDeclineAll={() => {
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
              onOpenDetail={(item, trigger) => {
                detailOverlay.openOverlay(
                  item.request_id,
                  trigger,
                  inboxItemToSeedRequest(item),
                )
              }}
            />
          ) : (
            <div className="flex h-full items-center justify-center p-8 text-xs text-ink-soft">
              {loading ? 'Loading review queue…' : 'Select a request to review.'}
            </div>
          )}
        </div>
        </div>
      </div>
      <RequestDetailOverlay
        requestId={detailOverlay.requestId}
        open={detailOverlay.open}
        onOpenChange={detailOverlay.onOpenChange}
        returnFocusRef={detailOverlay.returnFocusRef}
        seedRequest={detailOverlay.seedRequest}
      />
    </section>
  )
}
