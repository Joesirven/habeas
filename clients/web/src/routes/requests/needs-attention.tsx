import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import type { LegalInboxFilter, NeedsAttentionSearch } from '@/router'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  AccessDeliveryEmailCard,
  useIsAccessRequest,
} from '@/components/fulfillment/AccessDeliveryEmail'
import {
  AccessHandoffPanel,
  DropResponseStatusPicker,
  InboxConnectorNotificationsPanel,
  MatchingReviewPanel,
  MatchedContactsPanel,
  OwnerFulfillmentStatusPanel,
  isAutomaticFulfillmentVertical,
  matchingDispositionCopy,
  ownerDropStatusLabel,
  ownerFulfillmentVerticalRows,
  ownerStatusErrorMessage,
  useMatchingConnectorGate,
} from '@/components/requests/RequestTriageDialog'
import { MatchingResultsLabView } from '@/components/matching-results-lab/MatchingResultsLabView'
import { InboxViewSettingsPopover } from '@/components/inbox/InboxViewSettingsPopover'
import { InboxMatchingDispositionCard } from '@/components/requests/InboxMatchingDispositionCard'
import {
  Auth0MatchCandidatesList,
  RequestDetailOverlay,
  FulfillmentGateControls,
  isAuth0MatchingScope,
  JourneyStageSubsteps,
  REQUEST_DETAIL_TAB_TRIGGER,
  RequestDetailSideColumn,
  RequestDetailWorkbenchShell,
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { isLegalAdminPersona, isVerticalOperatorRole, useMe } from '@/lib/auth'
import {
  DROP_RESPONSE_STATUS_OPTIONS,
  dropResponseStatusLabel,
  getDropMatchingResultDetail,
  fetchOwnerVerticalMatchingDetailOptional,
  getFulfillmentArtifact,
  getLatestIdentityVerification,
  getLegalNeedsAttention,
  getLegalOperators,
  listVerticalMembers,
  getNeedsAttention,
  getOwnerFulfillmentNeedsAttention,
  getOwnerMatchingNeedsAttention,
  isOwnerVerticalTask,
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
  type ConnectorReminder,
  type MatchingResultDetail,
  type NeedsAttentionFilterOption,
  type NeedsAttentionItem,
  type RequestRecord,
  type TimelineEntry,
  type WorkbenchVerticalBatchRow,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import {
  ownerConnectorsSearch,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import {
  buildInboxGroupingStacks,
  groupInboxConnectorNotifications,
  inboxBatchStatusStackSubtitle,
  inboxDateSourceLabel,
  inboxItemConnectorBlock,
  inboxItemsConnectorBlock,
  type InboxConnectorBlock,
} from '@/lib/inbox-batch-status'
import {
  coalesceInboxReviewItems,
  expandInboxReviewBySystem,
  inboxItemConnections,
  inboxItemHasSystem,
  inboxSystemFilterOptions,
  isInboxIdentifierSurface,
  inboxReviewItemKey,
  inboxReviewItemSystemLabel,
  inboxReviewItemVerticalLabel,
  matchingReviewBulkPromoteToast,
  matchingReviewPostFields,
  matchingReviewPromoteToast,
  requestIdsFromSelectedReviewItems,
  selectedReviewTargets,
} from '@/lib/inbox-status-lab'
import {
  actionReasonLabel,
  aggregateOwnerSystemWorkbenchSubsteps,
  aggregateStackWorkbenchChrome,
  deriveWorkbenchChromeFromOpsJourney,
  formatStackSubstepCounts,
  isWorkbenchStageKey,
  matchingSystemColorClass,
  NOTICE_APPROVAL,
  opsStageToWorkbench,
  workbenchStatusLabel,
  type DerivedWorkbenchSubstep,
  type WorkbenchStageKey,
} from '@/lib/legalJourneyLabels'
import { cn, filterRequestUuids, isRequestUuid, paginate } from '@/lib/utils'

/** Left-pane queue page size — keeps the dense inbox list scannable without one giant scroll. */
const INBOX_PAGE_SIZE = 30
const INBOX_DETAIL_TAB_TRIGGER = REQUEST_DETAIL_TAB_TRIGGER

export const INBOX_LIST_COLLAPSED_KEY = 'inbox-list-collapsed'
/** Expanded left list (Inbox + Results lab). Collapsed rail stays a thin strip. */
export const INBOX_LIST_EXPANDED_COLS = 'md:grid-cols-[minmax(10rem,14rem)_minmax(0,1fr)]'
export const INBOX_LIST_COLLAPSED_COLS = 'md:grid-cols-[3rem_minmax(0,1fr)]'
export const INBOX_LIST_HOVER_FLYOUT =
  'md:absolute md:inset-y-0 md:left-0 md:z-20 md:w-[14rem] md:shadow-md'

const INBOX_STEP_KEYS = ['ingest', 'matching', 'fulfillment', 'notice'] as const
const INBOX_INTAKE_SOURCE_ORDER = ['drop', 'webform', 'csv', 'manual'] as const

export function useInboxListCollapsed(): {
  pinnedCollapsed: boolean
  hoverOpen: boolean
  effectiveCollapsed: boolean
  setPinnedCollapsed: (v: boolean) => void
  onRailEnter: () => void
  onRailLeave: () => void
} {
  const [pinnedCollapsed, setPinnedCollapsedState] = useState(() => {
    if (typeof window === 'undefined') return false
    try {
      return window.localStorage.getItem(INBOX_LIST_COLLAPSED_KEY) === '1'
    } catch {
      return false
    }
  })
  const [hoverOpen, setHoverOpen] = useState(false)

  const setPinnedCollapsed = useCallback((value: boolean) => {
    setPinnedCollapsedState(value)
    try {
      window.localStorage.setItem(INBOX_LIST_COLLAPSED_KEY, value ? '1' : '0')
    } catch {
      // private mode / quota — pin still works for this session
    }
  }, [])

  const onRailEnter = useCallback(() => {
    setHoverOpen(true)
  }, [])

  const onRailLeave = useCallback(() => {
    setHoverOpen(false)
  }, [])

  return {
    pinnedCollapsed,
    hoverOpen,
    effectiveCollapsed: pinnedCollapsed && !hoverOpen,
    setPinnedCollapsed,
    onRailEnter,
    onRailLeave,
  }
}

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

/** DWIDs for promote body: all/selected for 3/4, empty for 5, omit otherwise. */
function promoteDwidsForStatus(
  status: DropResponseStatusCode | undefined,
  dwids: string[] | undefined,
): { dwids?: string[] } {
  if (status === 5) return { dwids: [] }
  if ((status === 3 || status === 4) && dwids != null) return { dwids }
  return {}
}

async function resolvePromoteDwids(
  requestId: string,
  status: DropResponseStatusCode | undefined,
  selected?: string[],
): Promise<string[] | undefined> {
  if (status === 5) return []
  if (status !== 3 && status !== 4) return undefined
  if (selected != null) return selected
  try {
    const detail = await getDropMatchingResultDetail(requestId)
    return (detail.matched_contacts ?? []).map((contact) => contact.dwid)
  } catch {
    return undefined
  }
}

async function resolveOwnerPromoteDwids(
  requestId: string,
  vertical: string,
  system: string | undefined,
  status: DropResponseStatusCode | undefined,
): Promise<string[] | undefined> {
  if (status === 5) return []
  if (status !== 3 && status !== 4) return undefined
  try {
    const detail = await fetchOwnerVerticalMatchingDetailOptional(
      requestId,
      vertical,
      system,
    )
    return (detail?.matched_contacts ?? []).map((contact) => contact.dwid)
  } catch {
    return undefined
  }
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
  | 'fulfillment'
  | 'pending_tasks'
type MatchFilter = 'all' | 'single_match' | 'multi_match' | 'not_found' | 'unknown'
type DueFilter = 'all' | 'overdue' | 'due_soon' | 'on_track'

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

/** Data-owner / employee queue — Matching · Fulfillment · Tasks (R61). */
export const DATA_OWNER_INBOX_KIND_TABS: { value: InboxKind; label: string }[] = [
  { value: 'matching', label: 'Matching' },
  { value: 'fulfillment', label: 'Fulfillment' },
  { value: 'pending_tasks', label: 'Tasks' },
]

export { isAutomaticFulfillmentVertical, ownerFulfillmentVerticalRows }

/** Kicked-off fulfillment still on the owner Inbox · Fulfillment lane (R61). */
export function isOwnerFulfillmentItem(item: NeedsAttentionItem): boolean {
  if (isTriageItem(item) || isNoticeItem(item) || isDeliveryItem(item)) return false
  if (isAssignmentToLegalItem(item)) return false
  const stage = (item.current_stage ?? '').trim().toLowerCase()
  const reason = (item.reason ?? '').trim().toLowerCase()
  return (
    stage === 'fulfillment' ||
    stage === 'fulfill' ||
    reason === 'fulfillment.kickoff' ||
    reason === 'fulfillment.owner'
  )
}

export { ownerStatusErrorMessage }

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

export function matchTypeLabel(
  matchType: string | null | undefined,
  ownerLanguage = false,
): string {
  if (!matchType) return 'No match data'
  if (matchType === 'single_match') return ownerLanguage ? 'Confirm match' : 'Single match'
  if (matchType === 'multi_match') return 'Multi-person'
  if (matchType === 'not_found') return ownerLanguage ? 'Not a match' : 'Not found'
  return matchType.replaceAll('_', ' ')
}

const OWNER_MATCH_RESULT_BY_CODE: Record<number, string> = {
  3: 'Confirm match',
  4: 'Multi-person',
  5: 'Not a match',
}

export function ownerMatchResultLabel(code: number): string {
  return OWNER_MATCH_RESULT_BY_CODE[code] ?? formatDropStatusCode(code)
}

/** Bulk / thread default — multi → 4, not-found → 5, else 3 (never hardcode 3). */
export function suggestedBulkFulfillStatus(
  items: Array<Pick<NeedsAttentionItem, 'match_type' | 'match_count'>>,
): DropResponseStatusCode {
  if (items.length === 0) return 3
  const suggestions = items.map((item) =>
    suggestedDropResponseStatus(item.match_type, item.match_count),
  )
  if (suggestions.some((code) => code === 4)) return 4
  if (suggestions.every((code) => code === 5)) return 5
  return suggestions[0] ?? 3
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
export function dropStatusPill(
  item: NeedsAttentionItem,
  matching?: MatchingResultDetail | null,
  ownerLanguage = false,
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

  if (ownerLanguage) {
    if (statusSet && code != null) {
      return { label: `Match result · ${ownerMatchResultLabel(code)}`, tone: 'set' }
    }
    if (code != null) {
      return { label: `Match result · ${ownerMatchResultLabel(code)}`, tone: 'pending' }
    }
    if (matchedPending) {
      return { label: 'Match result · pending', tone: 'pending' }
    }
    return { label: 'Match result · unknown', tone: 'unknown' }
  }

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
  dataOwnerPersona = false,
): boolean {
  // Owner scope is `user_vertical_assignments`, not request-level assignee.
  if (dataOwnerPersona) return false
  return true
}

export function inboxItemTitle(item: NeedsAttentionItem): string {
  if (isTriageItem(item)) {
    const state = item.requestor_state?.trim()
    return state ? `Hold · ${state}` : 'Pre-matching hold'
  }
  if (isAssignmentToLegalItem(item)) return 'Assignment to legal'
  if (isEscalationItem(item)) return 'Assignment to legal'
  if (isDeliveryItem(item)) return 'Access delivery'
  if (isNoticeItem(item)) return 'Fulfillment notice'
  if (isCommsItem(item)) return 'Communications'
  if (isOwnerFulfillmentItem(item)) return 'Fulfillment'
  const connections = inboxItemConnections({
    request_id: item.request_id,
    system: inboxItemSystemId(item),
    system_label: item.system_label,
    connections: item.connections,
  })
  if (connections.length > 1) {
    return isMatchingItem(item) ? 'Matching review' : reasonLabel(item.reason)
  }
  const systemName = inboxReviewItemSystemLabel({
    request_id: item.request_id,
    system: inboxItemSystemId(item),
    system_label: item.system_label,
    vertical: item.vertical,
  })
  if (systemName) return systemName
  if (isFulfillmentLegalItem(item)) return 'Pre-fulfillment'
  return reasonLabel(item.reason)
}

/** Catalog system id — `system`, then `system_id`. Never a composite POST key. */
export function inboxItemSystemId(
  item: Pick<NeedsAttentionItem, 'system' | 'system_id'>,
): string | null {
  return item.system?.trim() || item.system_id?.trim() || null
}

export type InboxCatalogSearch = NeedsAttentionSearch & {
  vertical?: string
  system?: string
}

/**
 * Inbox URL merge — key presence so All/clear works.
 * Omit the key → keep current. Pass explicit `undefined` → clear.
 */
export function mergeInboxCatalogSearch(
  current: {
    bulk?: number
    kind?: InboxCatalogSearch['kind']
    filter?: InboxCatalogSearch['filter']
    assignee?: string
    vertical?: string
    system?: string
    source?: string
    step?: string
  },
  patch: Partial<InboxCatalogSearch>,
): InboxCatalogSearch {
  const bulk = 'bulk' in patch ? patch.bulk : current.bulk
  const kind = 'kind' in patch ? patch.kind : current.kind
  const filter = 'filter' in patch ? patch.filter : current.filter
  const assignee = 'assignee' in patch ? patch.assignee : current.assignee
  const vertical = 'vertical' in patch ? patch.vertical : current.vertical
  const system = 'system' in patch ? patch.system : current.system
  const source = 'source' in patch ? patch.source : current.source
  const rawStep = 'step' in patch ? patch.step : current.step
  const step =
    rawStep === 'ingest' ||
    rawStep === 'matching' ||
    rawStep === 'fulfillment' ||
    rawStep === 'notice'
      ? rawStep
      : undefined
  const next: InboxCatalogSearch = {}
  if (bulk != null) next.bulk = bulk
  if (kind) next.kind = kind
  if (filter) next.filter = filter
  if (assignee) next.assignee = assignee
  if (vertical?.trim()) next.vertical = vertical.trim()
  if (system?.trim()) next.system = system.trim()
  if (source?.trim()) next.source = source.trim()
  if (step) next.step = step
  return next
}

/** Owner matching rows — hide verticals not in `me.verticals`. */
export function ownerVisibleInboxItems(
  items: NeedsAttentionItem[],
  assignedVerticals: readonly string[] | null | undefined,
): NeedsAttentionItem[] {
  const allowed = new Set(
    (assignedVerticals ?? []).map((id) => id.trim()).filter(Boolean),
  )
  return items.filter((item) => {
    if (!isMatchingItem(item)) return true
    const vertical = item.vertical?.trim()
    if (!vertical) return false
    return allowed.has(vertical)
  })
}

export function normalizeInboxItem(item: NeedsAttentionItem): NeedsAttentionItem {
  const system = inboxItemSystemId(item)
  if (!system || item.system === system) return item
  return { ...item, system }
}

function matchingReviewBody(item: NeedsAttentionItem): {
  vertical?: string
  system?: string
} {
  const fields = matchingReviewPostFields({
    request_id: item.request_id,
    vertical: item.vertical,
    system: inboxItemSystemId(item),
  })
  return {
    ...(fields.vertical ? { vertical: fields.vertical } : {}),
    ...(fields.system ? { system: fields.system } : {}),
  }
}

function inboxSystemIdentityToken(token?: string | null): string {
  const normalized = (token ?? '').trim().toLowerCase()
  return normalized === 'amber' ? 'slate' : normalized
}

export function inboxSystemTitleClass(token?: string | null): string {
  switch (inboxSystemIdentityToken(token)) {
    case 'mid':
      return 'text-habeas-mid'
    case 'light':
      return 'text-habeas-light'
    case 'teal':
      return 'text-teal-700'
    case 'slate':
      return 'text-ink'
    case 'navy':
      return 'text-habeas-navy'
    default:
      return 'text-ink'
  }
}

export function inboxSystemRailClass(token?: string | null): string {
  switch (inboxSystemIdentityToken(token)) {
    case 'mid':
      return 'border-l-habeas-mid'
    case 'light':
      return 'border-l-habeas-light'
    case 'teal':
      return 'border-l-teal-600'
    case 'slate':
      return 'border-l-slate-400'
    case 'sky':
      return 'border-l-sky-500'
    case 'navy':
      return 'border-l-habeas-navy'
    default:
      return token?.trim() ? 'border-l-habeas-navy' : ''
  }
}

export type InboxCatalogFilterPatch = {
  vertical?: string
  system?: string
}

/** Vertical change clears system so Inbox and Results lab cannot drift. */
export function inboxCatalogFilterChange(
  field: 'vertical' | 'system',
  next: string | undefined,
): InboxCatalogFilterPatch {
  return field === 'vertical' ? { vertical: next, system: undefined } : { system: next }
}

export function InboxCatalogSelect({
  label,
  value,
  options,
  onChange,
  allowAll = true,
  disabled = false,
}: {
  label: string
  value: string | undefined
  options: readonly { id: string; label: string }[]
  onChange: (next: string | undefined) => void
  allowAll?: boolean
  disabled?: boolean
}) {
  const lockedValue =
    !allowAll && !value && options.length === 1 ? options[0]?.id : value
  return (
    <label className="flex shrink-0 items-center gap-1 text-[0.6rem] uppercase tracking-wide text-mute">
      {label}
      <select
        className="h-7 max-w-[12rem] rounded-md border border-line bg-paper px-1.5 text-[0.65rem] font-medium normal-case tracking-normal text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-habeas-mid disabled:opacity-70"
        value={lockedValue ?? ''}
        aria-label={label}
        disabled={disabled}
        onChange={(event) => {
          const next = event.target.value
          onChange(next ? next : undefined)
        }}
      >
        {allowAll ? <option value="">All</option> : null}
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

/** data_owner / data_user never get a Vertical dropdown — assigned verticals only. Count is ignored. */
export function hideInboxVerticalFilter(
  dataOwnerPersona: boolean,
  _assignedVerticals?: readonly string[] | null,
): boolean {
  return dataOwnerPersona
}

export function inboxItemSourceIds(
  item: Pick<NeedsAttentionItem, 'intake_source'>,
): string[] {
  const intake = item.intake_source?.trim()
  if (!intake || isInboxIdentifierSurface(intake)) return []
  return [intake]
}

export function inboxItemSourceLabel(id: string): string {
  if (isInboxIdentifierSurface(id)) return id
  return SOURCE_LABELS[id] ?? id
}

/** Map ops `current_stage` into the four workbench steps. Unknown stages land on ingest. */
export function inboxItemStep(
  item: Pick<NeedsAttentionItem, 'current_stage'>,
): WorkbenchStageKey {
  return opsStageToWorkbench(item.current_stage ?? '') ?? 'ingest'
}

export function ownerAssignCandidateEmails(input: {
  verticalMemberEmails?: readonly string[]
  legalOperatorEmails?: readonly string[]
  superAdminEmails?: readonly string[]
}): string[] {
  const set = new Set<string>()
  for (const email of [
    ...(input.verticalMemberEmails ?? []),
    ...(input.legalOperatorEmails ?? []),
    ...(input.superAdminEmails ?? []),
  ]) {
    const trimmed = email.trim()
    if (trimmed) set.add(trimmed)
  }
  return [...set].sort((left, right) => left.localeCompare(right))
}

export function resolveInboxAssignCandidates(input: {
  dataOwnerPersona: boolean
  selfEmail?: string | null
  itemAssigneeEmails?: readonly string[]
  verticalMemberEmails?: readonly string[]
  operators?: readonly { email?: string | null; kind?: string | null }[]
}): string[] {
  const operators = input.operators ?? []
  const legalOperatorEmails = operators
    .filter((operator) => {
      const kind = (operator.kind ?? '').trim().toLowerCase()
      return kind === 'legal' || kind === 'legal_team'
    })
    .map((operator) => operator.email ?? '')
  const superAdminEmails = operators
    .filter((operator) => operator.kind === 'super_admin')
    .map((operator) => operator.email ?? '')
  if (input.dataOwnerPersona) {
    return ownerAssignCandidateEmails({
      verticalMemberEmails: input.verticalMemberEmails,
      legalOperatorEmails,
      superAdminEmails,
    })
  }
  const set = new Set<string>()
  if (input.selfEmail?.trim()) set.add(input.selfEmail.trim())
  for (const email of input.itemAssigneeEmails ?? []) {
    if (email.trim()) set.add(email.trim())
  }
  for (const operator of operators) {
    if (operator.email?.trim()) set.add(operator.email.trim())
  }
  return [...set].sort((left, right) => left.localeCompare(right))
}

export function stackMatchingStatusSummary(
  items: Array<Pick<NeedsAttentionItem, 'match_type'>>,
  ownerLanguage = false,
): { label: string; mixed: boolean } {
  let single = 0
  let multi = 0
  let notFound = 0
  let other = 0
  for (const item of items) {
    if (item.match_type === 'single_match') single += 1
    else if (item.match_type === 'multi_match') multi += 1
    else if (item.match_type === 'not_found') notFound += 1
    else other += 1
  }
  const parts: string[] = []
  if (single) parts.push(`${single} ${matchTypeLabel('single_match', ownerLanguage)}`)
  if (multi) parts.push(`${multi} ${matchTypeLabel('multi_match', ownerLanguage)}`)
  if (notFound) parts.push(`${notFound} ${matchTypeLabel('not_found', ownerLanguage)}`)
  if (other) parts.push(`${other} no match data`)
  const kinds = [single, multi, notFound].filter((count) => count > 0).length
  return {
    label: parts.join(' · ') || 'No match data',
    mixed: kinds > 1,
  }
}

/** Queue row density — readable titles and icons; stats stay icon + tooltip. */
const INBOX_QUEUE_ROW_BUTTON =
  'flex min-w-0 flex-1 flex-nowrap items-center gap-1.5 overflow-hidden px-1.5 py-1.5 pr-2 text-left text-xs leading-normal'
const INBOX_QUEUE_META = 'shrink-0 text-xs leading-normal text-mute'
const INBOX_QUEUE_ICON =
  'inline-flex h-4 w-4 shrink-0 items-center justify-center text-mute'

function InboxStatTip({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  )
}

function InboxHintGlyph({
  label,
  className,
  children,
}: {
  label: string
  className?: string
  children: ReactNode
}) {
  return (
    <InboxStatTip label={label}>
      <span className={cn(INBOX_QUEUE_ICON, className)} aria-label={label}>
        {children}
      </span>
    </InboxStatTip>
  )
}

function InboxClockGlyph() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden>
      <circle
        cx="8"
        cy="8"
        r="5.25"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
      />
      <path
        d="M8 5.25V8l2 1.25"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
      />
    </svg>
  )
}

function inboxMatchHintKind(
  matchType: string | null | undefined,
  fallbackLabel?: string | null,
): string {
  if (matchType) return matchType
  const label = fallbackLabel ?? ''
  if (label === 'Exact 1:1' || label === 'Confirm match') return 'single_match'
  if (label === 'Multi-person') return 'multi_match'
  if (label === 'Not found' || label === 'Not a match') return 'not_found'
  return 'other'
}

function InboxMatchHint({
  matchType,
  dataOwnerPersona,
  label: labelOverride,
}: {
  matchType?: string | null
  dataOwnerPersona: boolean
  label?: string | null
}) {
  const kind = inboxMatchHintKind(matchType, labelOverride)
  const label = labelOverride ?? matchTypeLabel(matchType, dataOwnerPersona)
  return (
    <InboxHintGlyph label={label} className="w-auto min-w-4 gap-px px-0.5">
      {kind === 'multi_match' ? (
        <>
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500/70" aria-hidden />
        </>
      ) : kind === 'not_found' ? (
        <span
          className="h-1.5 w-1.5 rounded-full border border-slate-400 bg-transparent"
          aria-hidden
        />
      ) : kind === 'other' ? (
        <span className="h-1.5 w-1.5 rounded-full bg-slate-300" aria-hidden />
      ) : (
        <span className="h-1.5 w-1.5 rounded-full bg-habeas-navy" aria-hidden />
      )}
    </InboxHintGlyph>
  )
}

function inboxDueHintLabel(item: NeedsAttentionItem): string {
  const when = formatDueWhen(item)
  if (!when) return 'No due date'
  const bucket = dueBucket(item)
  if (bucket === 'overdue') return ['Overdue', when].join(' · ')
  if (bucket === 'due_soon') return ['Due soon', when].join(' · ')
  return ['Due', when].join(' ')
}

function InboxDueHint({ item }: { item: NeedsAttentionItem }) {
  const when = formatDueWhen(item)
  if (!when) return null
  const bucket = dueBucket(item)
  const label = inboxDueHintLabel(item)
  return (
    <InboxHintGlyph
      label={label}
      className={cn(
        'ml-auto',
        bucket === 'overdue' && 'text-red-700',
        bucket === 'due_soon' && 'text-amber-700',
      )}
    >
      {bucket === 'overdue' ? (
        <span className="text-[0.7rem] font-bold leading-none">!</span>
      ) : (
        <InboxClockGlyph />
      )}
    </InboxHintGlyph>
  )
}

function InboxCountHint({ count }: { count: number }) {
  const label = count === 1 ? '1 request' : `${count} requests`
  return (
    <InboxStatTip label={label}>
      <span className={cn(INBOX_QUEUE_META, 'tabular-nums')} aria-label={label}>
        {count}
      </span>
    </InboxStatTip>
  )
}

function InboxVerticalHint({ label }: { label: string }) {
  return (
    <InboxHintGlyph label={label}>
      <span className="h-1.5 w-1.5 rounded-[1px] bg-slate-400" aria-hidden />
    </InboxHintGlyph>
  )
}

function InboxConnectorStatusHint({ block }: { block: InboxConnectorBlock | null }) {
  if (!block) return null
  return (
    <span
      className="shrink-0 text-[0.6rem] font-medium text-amber-800"
      aria-label={block.label}
    >
      {block.label}
    </span>
  )
}

function InboxConnectorStatusChrome({
  block,
  verticalId,
  showWizard,
}: {
  block: InboxConnectorBlock | null
  verticalId?: string | null
  showWizard: boolean
}) {
  if (!block) return null
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="status"
      aria-label={block.label}
    >
      <span className="text-[0.7rem] font-medium text-amber-900">{block.label}</span>
      {showWizard ? (
        <Button asChild size="sm" variant="outline">
          <Link to="/owner/connectors" search={ownerConnectorsSearch(verticalId)}>
            Open connectors
          </Link>
        </Button>
      ) : null}
    </div>
  )
}

/** Shared Inbox / Results lab catalog toolbar — Vertical only. System lives in the popover. */
export function InboxCatalogFilterToolbar({
  vertical,
  verticalOptions,
  onPatch,
  hideVertical = false,
}: {
  vertical: string | undefined
  verticalOptions: readonly { id: string; label: string }[]
  onPatch: (patch: InboxCatalogFilterPatch) => void
  hideVertical?: boolean
}) {
  if (hideVertical) return null
  return (
    <>
      <InboxCatalogSelect
        label="Vertical"
        value={vertical}
        options={verticalOptions}
        onChange={(next) => onPatch(inboxCatalogFilterChange('vertical', next))}
      />
      <span
        className="mx-1.5 h-6 w-px shrink-0 self-center bg-line"
        aria-hidden
      />
    </>
  )
}

export function catalogOptionsFromItems(
  items: NeedsAttentionItem[],
  field: 'vertical' | 'system',
): NeedsAttentionFilterOption[] {
  const seen = new Map<string, NeedsAttentionFilterOption>()
  for (const item of items) {
    if (field === 'vertical') {
      const id = item.vertical?.trim()
      if (!id || seen.has(id)) continue
      seen.set(id, {
        id,
        label: inboxReviewItemVerticalLabel(item) ?? id,
      })
      continue
    }
    const id = inboxItemSystemId(item)
    if (!id || seen.has(id)) continue
    const label = inboxReviewItemSystemLabel({
      request_id: item.request_id,
      system: id,
      system_label: item.system_label,
      vertical: item.vertical,
    })
    if (!label) continue
    seen.set(id, {
      id,
      label,
      vertical: item.vertical?.trim() || undefined,
      color_token: item.color_token,
    })
  }
  return [...seen.values()]
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

export type DueBucket = 'overdue' | 'due_soon' | 'on_track' | 'unknown'

export function dueBucket(item: NeedsAttentionItem, now = Date.now()): DueBucket {
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
  if (bucket === 'overdue') return 'Overdue'
  if (bucket === 'due_soon') return `Due soon · ${when}`
  return `Due ${when}`
}

/** Colored due/SLA pill for the detail pane — list rows use InboxDueHint. */
export function DuePill({
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
      ? 'Overdue'
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

export function InboxPaginationBar({
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

export function FilterChip({
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
  matchingReviewLabel,
  ownerAssignMode = false,
}: {
  currentEmail: string | null | undefined
  currentGroup?: 'legal' | 'data' | null
  candidates: string[]
  disabled: boolean
  pending: boolean
  error: string | null
  onAssign: (target: AssignTarget) => void
  /** Per-vertical matching review — never “assign this request.” */
  matchingReviewLabel?: string | null
  /** Data owners: vertical members + legal + super_admin only. */
  ownerAssignMode?: boolean
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
    !ownerAssignMode &&
    normalizedQuery.includes('@') &&
    normalizedQuery.length >= 3 &&
    !exactMatch

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
            aria-label={
              matchingReviewLabel
                ? assigned
                  ? `Assigned to legal · ${label}`
                  : 'Assign to legal'
                : assigned
                  ? `Assigned to ${label}`
                  : 'Assign to legal or a reviewer'
            }
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
              <span className="block text-[0.6rem] text-mute">
                {matchingReviewLabel ? 'Matching review' : 'Assignee'}
              </span>
              <span className="block truncate text-[0.7rem] font-medium text-ink">
                {label}
              </span>
            </span>
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-80 p-2" align="start">
          <p className="px-1.5 pb-1.5 text-[0.65rem] text-mute">
            {ownerAssignMode
              ? 'Assign to a teammate on this vertical, legal, or an admin'
              : matchingReviewLabel
                ? 'Assign this request to legal. Owner matching review is a vertical catalog assignment, not this picker.'
                : 'Assign to legal, or claim this legal item'}
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
              ownerAssignMode || matchingReviewLabel
                ? ([
                    {
                      group: 'legal' as const,
                      title: 'Legal',
                      hint: ownerAssignMode
                        ? 'Legal team'
                        : 'Assign to legal — request journey',
                    },
                  ] as const)
                : ([
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
                  ] as const)
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
                  ? matchingReviewLabel
                    ? 'No matching people. Type a full email to assign to legal.'
                    : 'No matching people. Type a full email to assign.'
                  : matchingReviewLabel
                    ? 'No known legal reviewers yet.'
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
      hint: 'Claim this legal item for your queue',
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

export function inboxItemToSeedRequest(item: NeedsAttentionItem): RequestRecord {
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
  const requestIdReady = isRequestUuid(requestId)

  const timelineQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'timeline'],
    queryFn: () => getRequestTimeline(requestId),
    enabled: requestIdReady,
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

type InboxWorkbenchTab = 'overview' | WorkbenchStageKey

/** Dense ops summary for Inbox Overview tab — request + process context. */
function RequestProcessSummary({
  item,
  matching,
  identity,
  identityPending,
  legalPersona = false,
  dataOwnerPersona = false,
}: {
  item: NeedsAttentionItem
  matching?: MatchingResultDetail | null
  identity?: IdentityVerificationRecord | null
  identityPending?: boolean
  legalPersona?: boolean
  dataOwnerPersona?: boolean
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
  if (dataOwnerPersona) {
    ownerValue = item.vertical_label?.trim() || item.vertical?.trim() || '—'
  } else if (!showInboxIndividualAssignee(item, legalPersona, dataOwnerPersona)) {
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
    { label: dataOwnerPersona ? 'Vertical' : 'Owner', value: ownerValue },
    { label: 'Identity', value: identityValue, fullWidth: true },
  ]
  if (matchType || reviewStatus) {
    rows.push({
      label: 'Matching',
      value: [
        matchType ? matchTypeLabel(matchType, dataOwnerPersona) : null,
        matchCount != null ? `${matchCount} matches` : null,
        matchingStatusLabel(reviewStatus),
      ]
        .filter(Boolean)
        .join(' · '),
    })
  }
  if (recommended != null) {
    rows.push({
      label: dataOwnerPersona ? 'Match result' : 'DROP response',
      value: dataOwnerPersona
        ? ownerMatchResultLabel(recommended)
        : formatDropStatusCode(recommended),
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

export function InboxReviewPane({
  item,
  canReviewActions,
  assigneeCandidates,
  legalPersona = false,
  dataOwnerPersona = false,
  inboxKind,
  onBackToQueue,
  onOpenDetail,
}: {
  item: NeedsAttentionItem
  canReviewActions: boolean
  assigneeCandidates: string[]
  /** Legal case-queue mode — no matching disposition; status-required composer. */
  legalPersona?: boolean
  /** Owner-language matching selector (Confirm match / Multi-person / Not a match). */
  dataOwnerPersona?: boolean
  inboxKind?: InboxKind
  onBackToQueue?: () => void
  onOpenDetail?: (item: NeedsAttentionItem, trigger: HTMLElement) => void
}) {
  const queryClient = useQueryClient()
  const { me, isAdmin } = useMe()
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
  const [tab, setTab] = useState<InboxWorkbenchTab>('overview')
  const [matchingBatchDefault, setMatchingBatchDefault] = useState<string | null>(null)
  const [matchingUseBatchDefault, setMatchingUseBatchDefault] = useState(true)
  const [activeConnectionSystem, setActiveConnectionSystem] = useState<string | null>(
    () => inboxItemSystemId(item),
  )
  const isAccessRequest = useIsAccessRequest(item.request_id)
  const reviewItemKey = inboxReviewItemKey(item)

  const showTriage = isTriageItem(item)
  const showAssignmentToLegal = legalPersona && isAssignmentToLegalItem(item)
  const showOwnerFulfillmentPane =
    dataOwnerPersona &&
    (inboxKind === 'fulfillment' || isOwnerFulfillmentItem(item))
  const showMatching =
    isMatchingItem(item) &&
    !isDeliveryItem(item) &&
    !isNoticeItem(item) &&
    !showTriage &&
    !legalPersona &&
    !showOwnerFulfillmentPane
  const showDelivery =
    !showOwnerFulfillmentPane &&
    (isDeliveryItem(item) || item.current_stage === 'fulfill')
  const showNotice = isNoticeItem(item)
  const showComms = isCommsItem(item) && !legalPersona
  const requestIdReady = isRequestUuid(item.request_id)

  const ownerVertical = dataOwnerPersona ? item.vertical?.trim() || null : null
  const ownerSystem = dataOwnerPersona
    ? (activeConnectionSystem ?? inboxItemSystemId(item))
    : null

  // Matching detail for review + notice (post-fulfill summary still needs match info).
  // Owners load the vertical-item payload — never the whole-request DROP URL.
  const matchingQuery = useQuery({
    queryKey: ownerVertical
      ? [
          'admin-api',
          'ops',
          'requests',
          item.request_id,
          'verticals',
          ownerVertical,
          ownerSystem,
          'matching-results',
        ]
      : ['admin-api', 'ops', 'drop', 'matching-results', item.request_id],
    queryFn: () =>
      ownerVertical
        ? fetchOwnerVerticalMatchingDetailOptional(
            item.request_id,
            ownerVertical,
            ownerSystem ?? undefined,
          )
        : fetchMatchingDetailOptional(item.request_id),
    enabled: requestIdReady && (!dataOwnerPersona || Boolean(ownerVertical)),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'journey'],
    queryFn: () => getRequestJourney(item.request_id),
    enabled: requestIdReady,
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
    enabled: requestIdReady,
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
    retry: false,
  })

  const artifactQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', item.request_id],
    queryFn: () => getFulfillmentArtifact(item.request_id),
    enabled: requestIdReady,
    refetchInterval: 15_000,
    retry: false,
  })

  const identityQuery = useQuery({
    queryKey: ['admin-api', 'requests', item.request_id, 'identity-verification'],
    queryFn: () => getLatestIdentityVerification(item.request_id),
    enabled: requestIdReady,
    refetchInterval: 15_000,
    retry: false,
  })

  const commentsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'comments'],
    queryFn: () => getRequestComments(item.request_id),
    enabled: requestIdReady,
    refetchInterval: 15_000,
  })

  const requestQuery = useQuery({
    queryKey: ['admin-api', 'requests', item.request_id],
    queryFn: () => getRequest(item.request_id),
    enabled: requestIdReady,
    refetchInterval: 30_000,
    placeholderData: (previous) => previous,
  })

  const suggestedStatus = recommendedStatusFromItem(item, matchingQuery.data)
  const matchedContacts = matchingQuery.data?.matched_contacts ?? []
  const contactDwids = matchedContacts.map((contact) => contact.dwid)
  const [fulfillStatus, setFulfillStatus] = useState<DropResponseStatusCode | null>(() =>
    recommendedStatusFromItem(item),
  )
  const [selectedDwids, setSelectedDwids] = useState<string[]>(() => {
    const initial = recommendedStatusFromItem(item)
    return initial === 3 || initial === 4 ? contactDwids : []
  })

  const handleFulfillStatusChange = (code: DropResponseStatusCode) => {
    setFulfillStatus(code)
    if (code === 5) {
      setSelectedDwids([])
      return
    }
    if (code === 3 || code === 4) {
      setSelectedDwids(matchedContacts.map((contact) => contact.dwid))
    }
  }

  const fulfillNeedsDwids = fulfillStatus === 3 || fulfillStatus === 4
  // Require explicit DWID selection for 3/4 — empty contacts must not enable confirm.
  const fulfillDwidsReady = !fulfillNeedsDwids || selectedDwids.length > 0

  const promoteMutation = useMutation({
    mutationFn: ({
      responseStatus,
      dwids,
    }: {
      responseStatus: DropResponseStatusCode
      dwids?: string[]
    }) =>
      postDropMatchingResultPromote(item.request_id, {
        response_status: responseStatus,
        ...promoteDwidsForStatus(responseStatus, dwids),
        ...matchingReviewBody({
          ...item,
          system: ownerSystem ?? inboxItemSystemId(item) ?? item.system,
        }),
      }),
    onSuccess: async (data) => {
      setConfirmAction(null)
      const copy = matchingReviewPromoteToast(data)
      if (copy.variant === 'warning') {
        actionToast.warning({ title: copy.title, description: copy.description })
      } else {
        actionToast.success({ title: copy.title, description: copy.description })
      }
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
    mutationFn: () =>
      postDropMatchingResultDecline(
        item.request_id,
        matchingReviewBody({
          ...item,
          system: ownerSystem ?? inboxItemSystemId(item) ?? item.system,
        }),
      ),
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
        if (target.group !== 'legal') {
          throw new Error(
            'Owner matching review is a vertical catalog assignment, not a request assignment.',
          )
        }
        return postDropWorkflowEscalate({
          request_ids: [item.request_id],
          target_role: 'legal',
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
              if (item.vertical && row.vertical && row.vertical !== item.vertical) {
                return row
              }
              if (target.kind === 'group') {
                return {
                  ...row,
                  assignment: {
                    kind: 'escalate',
                    target_role: 'legal',
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
  const dropPill = dropStatusPill(item, matchingQuery.data, dataOwnerPersona)
  /** Open the stage that holds the current job; Overview otherwise. */
  const primaryTab: InboxWorkbenchTab = showTriage
    ? 'ingest'
    : showAssignmentToLegal || showMatching
      ? 'matching'
      : showNotice
        ? 'notice'
        : showHandoffTab || showOwnerFulfillmentPane
          ? 'fulfillment'
          : 'overview'

  useEffect(() => {
    setTab(primaryTab)
  }, [reviewItemKey, primaryTab])

  useEffect(() => {
    setActiveConnectionSystem(inboxItemSystemId(item))
  }, [reviewItemKey, item.system, item.system_id])

  const matchingStatusOptions = useMemo(
    () =>
      DROP_RESPONSE_STATUS_OPTIONS.map((row) => ({
        id: String(row.code),
        label: dataOwnerPersona ? (ownerDropStatusLabel(row.code) ?? row.label) : row.label,
      })),
    [dataOwnerPersona],
  )

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
          ? 'Confirm the match disposition.'
          : showOwnerFulfillmentPane
            ? 'Legal kicked off fulfillment. Mark each owned SaaS system; Data runs automatically.'
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
      <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
        <ConfirmActionDialog
          open={confirmAction === 'fulfill'}
          onOpenChange={(open) => {
            if (!open && !actionPending) setConfirmAction(null)
            if (open) {
              setFulfillStatus(suggestedStatus)
              setSelectedDwids(
                suggestedStatus === 3 || suggestedStatus === 4
                  ? matchedContacts.map((contact) => contact.dwid)
                  : [],
              )
            }
          }}
          title={matchingDispositionCopy(dataOwnerPersona ? 'data_owner' : legalPersona ? 'legal' : 'ops').confirmTitle}
          description={matchingDispositionCopy(dataOwnerPersona ? 'data_owner' : legalPersona ? 'legal' : 'ops').confirmDescription(item.request_id.slice(0, 8))}
          confirmLabel={matchingDispositionCopy(dataOwnerPersona ? 'data_owner' : legalPersona ? 'legal' : 'ops').confirmLabel}
          confirming={actionPending && confirmAction === 'fulfill'}
          confirmDisabled={fulfillStatus == null || !fulfillDwidsReady}
          onConfirm={() => {
            if (fulfillStatus == null) return
            const dwids = fulfillStatus === 5 ? [] : selectedDwids
            promoteMutation.mutate({ responseStatus: fulfillStatus, dwids })
          }}
        >
          <DropResponseStatusPicker
            value={fulfillStatus}
            onChange={handleFulfillStatusChange}
            disabled={actionPending}
            suggested={suggestedStatus}
            contacts={matchedContacts}
            selectedDwids={selectedDwids}
            onSelectedDwidsChange={setSelectedDwids}
            persona={dataOwnerPersona ? 'data_owner' : legalPersona ? 'legal' : 'ops'}
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
          title="Assign to legal?"
          description={`Send this matching review to Legal Inbox for the request journey. Add a comment first if context is needed.`}
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

        <RequestDetailWorkbenchShell
          header={
        <div className="shrink-0 space-y-1.5 border-b border-line px-3 py-2">
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
                {item.color_token ? (
                  <span
                    className={cn(
                      'h-2.5 w-2.5 shrink-0 rounded-full border',
                      matchingSystemColorClass(item.color_token),
                    )}
                    aria-hidden
                  />
                ) : null}
                <h2
                  className={cn(
                    'text-sm font-semibold',
                    inboxSystemTitleClass(item.color_token),
                  )}
                >
                  {inboxItemTitle(item)}
                </h2>
                <DuePill item={item} />
              </div>
              <InboxConnectorStatusChrome
                block={inboxItemConnectorBlock(item, {
                  reminders: me?.connector_reminders,
                  matchingDetail: matchingQuery.data,
                })}
                verticalId={item.vertical}
                showWizard={dataOwnerPersona}
              />
              <p className="font-mono text-[0.65rem] text-ink-soft">
                {item.request_id}
                <span className="font-sans text-mute">
                  {' '}
                  · {SOURCE_LABELS[item.intake_source] ?? item.intake_source}
                  {item.vertical_label || item.vertical
                    ? ` · ${item.vertical_label || item.vertical}`
                    : ''}
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
              ownerAssignMode={dataOwnerPersona}
              matchingReviewLabel={
                dataOwnerPersona || legalPersona
                  ? null
                  : item.vertical_label?.trim() || item.vertical?.trim() || 'this vertical'
              }
            />
          </div>

          {/* 2. Next step — one clear job for the eye */}
          {showMatching && !legalPersona ? (
            <InboxMatchingDispositionCard
              canReviewActions={canReviewActions}
              actionPending={actionPending}
              dataOwnerPersona={dataOwnerPersona}
              onConfirm={() => setConfirmAction('fulfill')}
              onDecline={() => setConfirmAction('decline')}
              onEscalate={() => setConfirmAction('escalate')}
              onSeeMoreDetails={(trigger) => onOpenDetail?.(item, trigger)}
            />
          ) : null}
          {(!showMatching || legalPersona) && (nextStepHint || canReviewActions) ? (
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
              {showOwnerFulfillmentPane ? (
                <div className={cn(nextStepHint && 'mt-1.5')}>
                  <OwnerFulfillmentStatusPanel
                    requestId={item.request_id}
                    cluster={kickoffRows}
                    assignedVerticals={me?.verticals}
                    assignedLabels={me?.assigned_vertical_labels}
                    canSubmit={canReviewActions}
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
                {!showMatching ? (
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
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
          }
          rail={
            <ThinJourneyPipeline
              stages={pipelineStages}
              substeps={pipelineSubsteps}
              matchingCluster={workbench?.matching_cluster}
              fulfillmentCluster={workbench?.fulfillment_cluster}
              splitPosture={workbench?.split_posture ?? derivedChrome?.split_posture}
              density="compact"
              showSubsteps={false}
              expandedStage={isWorkbenchStageKey(tab) ? tab : null}
              onStageActivate={(stage) => {
                if (isWorkbenchStageKey(stage)) setTab(stage)
              }}
            />
          }
          side={
            <RequestDetailSideColumn
              activity={
                <InboxActivityPanel
                  requestId={item.request_id}
                  canCompose={false}
                />
              }
              comments={
                <div className="flex min-h-0 flex-col space-y-2">
                  <p className="text-[0.6rem] font-medium uppercase tracking-wide text-mute">
                    {showAssignmentToLegal ? 'Assignment thread' : 'Comments'}
                    {comments.length > 0 ? (
                      <span className="ml-1 tabular-nums opacity-70">({comments.length})</span>
                    ) : null}
                  </p>
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
                </div>
              }
            />
          }
        >
        <Tabs
          key={inboxReviewItemKey(item)}
          value={tab}
          onValueChange={(value) => {
            if (value === 'overview' || isWorkbenchStageKey(value)) {
              setTab(value)
            }
          }}
          className="flex h-full min-h-0 flex-1 flex-col overflow-hidden"
        >
          <div className="shrink-0 border-b border-line px-3 py-1">
            <TabsList
              className="h-8 w-full justify-start gap-1 overflow-x-auto rounded-md border border-line bg-canvas p-0.5"
              aria-label="Request detail sections"
            >
              <TabsTrigger value="overview" className={INBOX_DETAIL_TAB_TRIGGER}>
                Overview
              </TabsTrigger>
              <TabsTrigger value="ingest" className={INBOX_DETAIL_TAB_TRIGGER}>
                Ingest
              </TabsTrigger>
              <TabsTrigger value="matching" className={INBOX_DETAIL_TAB_TRIGGER}>
                Matching
              </TabsTrigger>
              <TabsTrigger value="fulfillment" className={INBOX_DETAIL_TAB_TRIGGER}>
                Fulfillment
              </TabsTrigger>
              <TabsTrigger value="notice" className={INBOX_DETAIL_TAB_TRIGGER}>
                Notice
              </TabsTrigger>
            </TabsList>
          </div>

          <div
            className={cn(
              'min-h-0 flex-1 px-3 py-2.5',
              showMatching && tab === 'matching' ? 'overflow-hidden' : 'overflow-y-auto',
            )}
          >
            <TabsContent value="overview" className="mt-0 max-h-full space-y-3 overflow-y-auto">
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
              {dataOwnerPersona && showMatching ? (
                <MatchedContactsPanel matching={matchingQuery.data ?? undefined} />
              ) : (
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
              )}
              <RequestProcessSummary
                item={item}
                matching={matchingQuery.data}
                identity={identityQuery.data}
                identityPending={identityQuery.isPending}
                legalPersona={legalPersona}
                dataOwnerPersona={dataOwnerPersona}
              />
            </TabsContent>

            <TabsContent value="ingest" className="mt-0 max-h-full space-y-3 overflow-y-auto">
              <JourneyStageSubsteps
                stages={pipelineStages}
                stageKey="ingest"
                substeps={pipelineSubsteps}
                density="compact"
              />
              {showTriage ? (
                <div className="space-y-2 text-xs">
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
                </div>
              ) : null}
            </TabsContent>

            <TabsContent
              value="matching"
              className={cn(
                'mt-0 space-y-3',
                showMatching && 'flex h-full min-h-0 flex-col overflow-hidden',
              )}
            >
              {showMatching ? (
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                  {isAuth0MatchingScope(item.vertical, inboxItemSystemId(item)) ? (
                    <div className="shrink-0 pb-3">
                      <Auth0MatchCandidatesList requestId={item.request_id} />
                    </div>
                  ) : null}
                  <div className="min-h-0 flex-1 overflow-y-auto">
                    <MatchingResultsLabView
                      method="two-tier"
                      item={item}
                      detail={matchingQuery.data ?? null}
                      contacts={matchedContacts}
                      loading={matchingQuery.isPending}
                      ownerLanguage={dataOwnerPersona}
                      statusOptions={matchingStatusOptions}
                      statusId={
                        matchingUseBatchDefault && matchingBatchDefault
                          ? matchingBatchDefault
                          : fulfillStatus != null
                            ? String(fulfillStatus)
                            : null
                      }
                      onStatusChange={(next) => {
                        const code = Number(next) as DropResponseStatusCode
                        if (code === 3 || code === 4 || code === 5) {
                          handleFulfillStatusChange(code)
                        }
                        setMatchingUseBatchDefault(false)
                      }}
                      selectedDwids={selectedDwids}
                      onSelectedDwidsChange={setSelectedDwids}
                      disabled={!canReviewActions || legalPersona}
                      pending={actionPending}
                      onApply={(draft) => {
                        const raw = draft?.statusId ?? (fulfillStatus != null ? String(fulfillStatus) : null)
                        const code = Number(raw) as DropResponseStatusCode
                        if (code !== 3 && code !== 4 && code !== 5) return
                        const dwids = code === 5 ? [] : (draft?.selectedDwids ?? selectedDwids)
                        if ((code === 3 || code === 4) && dwids.length === 0) return
                        promoteMutation.mutate({ responseStatus: code, dwids })
                      }}
                      batchDefaultStatus={matchingBatchDefault ?? (suggestedStatus != null ? String(suggestedStatus) : null)}
                      onBatchDefaultStatusChange={(next) => {
                        setMatchingBatchDefault(next)
                        const code = Number(next) as DropResponseStatusCode
                        if (matchingUseBatchDefault && (code === 3 || code === 4 || code === 5)) {
                          handleFulfillStatusChange(code)
                        }
                      }}
                      useBatchDefault={matchingUseBatchDefault}
                      onUseBatchDefaultChange={setMatchingUseBatchDefault}
                      selectedCount={0}
                      onApplySelection={() => undefined}
                    />
                  </div>
                </div>
              ) : showResolveMatching ? (
                <>
                  <MatchingReviewPanel
                    requestId={item.request_id}
                    matching={matchingQuery.data}
                    isPending={matchingQuery.isPending}
                    isError={matchingQuery.isError}
                    canReviewActions={canReviewActions && !legalPersona}
                    actionPending={actionPending}
                    connectorReminders={me?.connector_reminders}
                    fetchConnectorConnections={isAdmin}
                    onPromote={(responseStatus, dwids) =>
                      promoteMutation.mutate({ responseStatus, dwids })
                    }
                    onDecline={() => declineMutation.mutate()}
                    compact
                    layout="tabs"
                    hideActions
                    persona={dataOwnerPersona ? 'data_owner' : legalPersona ? 'legal' : 'ops'}
                  />
                  {legalPersona && showAssignmentToLegal ? (
                    <p className="text-[0.7rem] text-ink-soft">
                      Matching is read-only here — use Start fulfillment in the next-step card
                      (or request detail Fulfillment tab) after disposition is recorded.
                    </p>
                  ) : null}
                </>
              ) : (
                <p className="text-[0.7rem] text-mute">
                  Matching detail appears when this request is in review.
                </p>
              )}
            </TabsContent>

            <TabsContent value="fulfillment" className="mt-0 max-h-full space-y-3 overflow-y-auto">
              <JourneyStageSubsteps
                stages={pipelineStages}
                stageKey="fulfillment"
                substeps={pipelineSubsteps}
                matchingCluster={workbench?.matching_cluster}
                fulfillmentCluster={workbench?.fulfillment_cluster}
                density="compact"
              />
              {showHandoffTab ? (
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
              ) : null}
              {showComms ? (
                <div className="text-xs text-ink-soft">
                  <p className="font-medium text-ink">Requester communications</p>
                  <p className="mt-1">
                    Outbound drafts, sent attempts, and inbound replies will thread here. Use
                    Access email below for access URL emails today.
                  </p>
                </div>
              ) : null}
              {isAccessRequest === true ? (
                <AccessDeliveryEmailCard requestId={item.request_id} />
              ) : null}
            </TabsContent>

            <TabsContent value="notice" className="mt-0 max-h-full space-y-3 overflow-y-auto">
              <JourneyStageSubsteps
                stages={pipelineStages}
                stageKey="notice"
                substeps={pipelineSubsteps}
                density="compact"
              />
              <p className="text-[0.75rem] text-ink-soft">
                After approval, fulfilled DROP rows enter the next weekly upload batch
                (America/Los_Angeles) — not a consumer delivery URL.
              </p>
            </TabsContent>
          </div>
        </Tabs>
        </RequestDetailWorkbenchShell>
      </div>
  )
}



export type InboxStackKind =
  | 'batch_type'
  | 'status'
  | 'batch_status'
  | 'system'
  | 'date_source'

export function inboxThreadMicroLabel(stackKind: InboxStackKind): string {
  switch (stackKind) {
    case 'system':
      return 'System'
    case 'status':
      return 'Status'
    case 'batch_type':
      return 'Batch · System'
    case 'batch_status':
      return 'Batch · Status'
    case 'date_source':
    default:
      return 'Batch'
  }
}

export function inboxStackCountCaption(count: number): string {
  return count === 1
    ? 'Counts across 1 request in this group.'
    : `Counts across ${count} requests in this group.`
}

export type InboxRow =
  | {
      kind: 'thread'
      stackKind: InboxStackKind
      batchKey: string
      batchLabel: string
      items: NeedsAttentionItem[]
    }
  | { kind: 'request'; item: NeedsAttentionItem }

export function findThreadRow(
  rows: InboxRow[],
  batchKey: string,
): Extract<InboxRow, { kind: 'thread' }> | null {
  for (const row of rows) {
    if (row.kind === 'thread' && row.batchKey === batchKey) return row
  }
  return null
}

/** Open a single request so the Matching-tab DWID selector is on screen — not a batch aggregate. */
export function firstIndividualInboxTarget(rows: InboxRow[]): {
  target: InboxActiveTarget
  expandBatchKey?: string
} | null {
  const firstRequest = rows.find(
    (row): row is Extract<InboxRow, { kind: 'request' }> => row.kind === 'request',
  )
  if (firstRequest) {
    return { target: { kind: 'request', itemKey: inboxReviewItemKey(firstRequest.item) } }
  }
  const firstThread = rows.find(
    (row): row is Extract<InboxRow, { kind: 'thread' }> => row.kind === 'thread',
  )
  if (!firstThread) return null
  const firstItem = firstThread.items[0]
  if (firstItem) {
    return {
      target: { kind: 'request', itemKey: inboxReviewItemKey(firstItem) },
      expandBatchKey: firstThread.batchKey,
    }
  }
  return { target: { kind: 'thread', batchKey: firstThread.batchKey } }
}

export function countThreadStacks(rows: InboxRow[]): number {
  return rows.filter((row) => row.kind === 'thread').length
}

/** Stack by date+source, system, and/or status. Multi-select is SQL GROUP BY. */
export function buildGroupedInboxRows(
  items: NeedsAttentionItem[],
  options: {
    byStatus?: boolean
    byDateSource?: boolean
    bySystem?: boolean
    reminders?: ConnectorReminder[] | null
    gate?: MatchingConnectorGate | null
  },
  ownerLanguage = false,
): InboxRow[] {
  const byDateSource = options.byDateSource ?? false
  const bySystem = options.bySystem ?? false
  const byStatus = options.byStatus ?? false
  if (!byDateSource && !bySystem && !byStatus) {
    return items.map((item) => ({ kind: 'request' as const, item }))
  }
  return buildInboxGroupingStacks(
    items,
    {
      byDateSource,
      bySystem,
      byStatus,
      reminders: options.reminders,
      gate: options.gate,
    },
    ownerLanguage,
  ).map((stack) => {
    const sorted = [...stack.items].sort((a, b) =>
      (a.requested_at ?? '').localeCompare(b.requested_at ?? ''),
    )
    const stackKind: InboxStackKind =
      byDateSource && byStatus
        ? 'batch_status'
        : byDateSource && bySystem
          ? 'batch_type'
          : byStatus
            ? 'status'
            : bySystem
              ? 'system'
              : 'date_source'
    return {
      kind: 'thread' as const,
      stackKind,
      batchKey: stack.key,
      batchLabel: stack.label,
      items: sorted,
    }
  })
}

export function InboxGroupSwitch({
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
export function coerceGroupedInboxRows(
  rows: InboxRow[],
  groupingActive: boolean,
): InboxRow[] {
  if (!groupingActive) return rows
  return rows.map((row) => {
    if (row.kind === 'thread') return row
    return {
      kind: 'thread',
      stackKind: 'date_source',
      batchKey: `singleton:${inboxReviewItemKey(row.item)}`,
      batchLabel: inboxItemTitle(row.item),
      items: [row.item],
    }
  })
}

export type InboxActiveTarget =
  | { kind: 'thread'; batchKey: string }
  | { kind: 'request'; itemKey: string }

type ActiveTarget = InboxActiveTarget

export function threadIsExactMatchBatch(items: NeedsAttentionItem[]): boolean {
  return items.length > 0 && items.every((entry) => entry.match_type === 'single_match')
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
    const countLabel = formatStackSubstepCounts(row.member_status_counts)
    return {
      vertical: row.vertical,
      label: row.label,
      live: row.live,
      matching_status: row.matching_status,
      fulfillment_status: row.fulfillment_status,
      blocker: countLabel || null,
    }
  })
}

/** Vertical cluster rows as countable substeps — never per-request match rows. */
function batchClusterAsSubsteps(
  rows: WorkbenchVerticalBatchRow[] | undefined,
  parent: 'matching' | 'fulfillment',
): DerivedWorkbenchSubstep[] {
  if (!rows?.length) return []
  return rows.map((row) => {
    const status =
      parent === 'matching'
        ? row.matching_status
        : (row.fulfillment_status ?? 'not_started')
    const countLabel = formatStackSubstepCounts(row.member_status_counts)
    return {
      key: `${parent}-${row.vertical}`,
      label: row.label,
      status,
      parent,
      blocker: null,
      statusLabel: countLabel || (row.live ? workbenchStatusLabel(status) : 'Soon'),
    }
  })
}

function countStackKeys(values: Array<string | null | undefined>): Array<{ key: string; count: number }> {
  const tallies = new Map<string, number>()
  for (const value of values) {
    const key = value?.trim() || 'unknown'
    tallies.set(key, (tallies.get(key) ?? 0) + 1)
  }
  return [...tallies.entries()]
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count)
}

function dueBucketLabel(bucket: string): string {
  if (bucket === 'overdue') return 'Overdue'
  if (bucket === 'due_soon') return 'Due soon'
  if (bucket === 'on_track') return 'On track'
  return 'No due date'
}

/** Stack-level counts only — never per-request match rows or DWID tables. */
function StackCollectiveSummary({
  items,
  dataOwnerPersona,
  showMatching = true,
}: {
  items: NeedsAttentionItem[]
  dataOwnerPersona: boolean
  showMatching?: boolean
}) {
  const matchRows = countStackKeys(items.map((item) => item.match_type))
  const dueRows = countStackKeys(items.map((item) => dueBucket(item)))
  const stageRows = countStackKeys(items.map((item) => item.current_stage ?? item.kind))
  const verticalRows = countStackKeys(
    items.map((item) => item.vertical_label || item.vertical),
  )
  const statusRows = countStackKeys(
    items.map((item) =>
      item.recommended_response_status != null
        ? String(item.recommended_response_status)
        : null,
    ),
  )

  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3">
        <div className="min-w-0">
          <dt className="text-[0.6rem] uppercase tracking-wide text-mute">In stack</dt>
          <dd className="text-xs font-medium tabular-nums text-ink">{items.length}</dd>
        </div>
        {dueRows.map((row) => (
          <div key={`due-${row.key}`} className="min-w-0">
            <dt className="text-[0.6rem] uppercase tracking-wide text-mute">
              {dueBucketLabel(row.key)}
            </dt>
            <dd className="text-xs font-medium tabular-nums text-ink">{row.count}</dd>
          </div>
        ))}
      </dl>
      {showMatching ? (
        <div>
          <p className="text-[0.6rem] uppercase tracking-wide text-mute">Match results</p>
          <ul className="mt-1 space-y-0.5">
            {matchRows.map((row) => (
              <li
                key={`match-${row.key}`}
                className="flex items-baseline justify-between gap-2 text-[0.7rem]"
              >
                <span className="text-ink">
                  {row.key === 'unknown'
                    ? 'No match data'
                    : matchTypeLabel(row.key, dataOwnerPersona)}
                </span>
                <span className="tabular-nums text-mute">{row.count}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {statusRows.some((row) => row.key !== 'unknown') ? (
        <div>
          <p className="text-[0.6rem] uppercase tracking-wide text-mute">
            {dataOwnerPersona ? 'Recommended result' : 'Recommended CA DROP'}
          </p>
          <ul className="mt-1 space-y-0.5">
            {statusRows.map((row) => (
              <li
                key={`status-${row.key}`}
                className="flex items-baseline justify-between gap-2 text-[0.7rem]"
              >
                <span className="text-ink">
                  {row.key === 'unknown'
                    ? 'Pending'
                    : dataOwnerPersona
                      ? ownerMatchResultLabel(Number(row.key))
                      : dropResponseStatusLabel(Number(row.key))}
                </span>
                <span className="tabular-nums text-mute">{row.count}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {verticalRows.some((row) => row.key !== 'unknown') ? (
        <div>
          <p className="text-[0.6rem] uppercase tracking-wide text-mute">Verticals</p>
          <ul className="mt-1 space-y-0.5">
            {verticalRows.map((row) => (
              <li
                key={`vert-${row.key}`}
                className="flex items-baseline justify-between gap-2 text-[0.7rem]"
              >
                <span className="text-ink">{row.key === 'unknown' ? 'Unassigned' : row.key}</span>
                <span className="tabular-nums text-mute">{row.count}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div>
        <p className="text-[0.6rem] uppercase tracking-wide text-mute">Stages</p>
        <ul className="mt-1 space-y-0.5">
          {stageRows.map((row) => (
            <li
              key={`stage-${row.key}`}
              className="flex items-baseline justify-between gap-2 text-[0.7rem]"
            >
              <span className="capitalize text-ink">{row.key.replaceAll('_', ' ')}</span>
              <span className="tabular-nums text-mute">{row.count}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function InboxEarliestComments({
  requestId,
  canCompose,
}: {
  requestId: string
  canCompose: boolean
}) {
  const queryClient = useQueryClient()
  const [commentDraft, setCommentDraft] = useState('')
  const requestIdReady = isRequestUuid(requestId)

  const commentsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'comments'],
    queryFn: () => getRequestComments(requestId),
    enabled: requestIdReady,
    refetchInterval: 15_000,
  })

  const commentMutation = useMutation({
    mutationFn: (body: string) => postRequestComment(requestId, body),
    onSuccess: async () => {
      setCommentDraft('')
      actionToast.success({ title: 'Comment posted' })
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'requests', requestId, 'comments'],
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

  const comments = commentsQuery.data ?? []

  return (
    <div className="flex min-h-0 flex-col space-y-2">
      <p className="text-[0.6rem] font-medium uppercase tracking-wide text-mute">
        Comments
        {comments.length > 0 ? (
          <span className="ml-1 tabular-nums opacity-70">({comments.length})</span>
        ) : null}
      </p>
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
            <p className="whitespace-pre-wrap text-[0.7rem] text-ink-soft">{comment.body}</p>
          </div>
        ))}
      </div>
      {canCompose ? (
        <div className="flex shrink-0 items-end gap-2 border-t border-line pt-2">
          <textarea
            className="min-h-[3.5rem] max-h-32 flex-1 resize-y rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
            value={commentDraft}
            onChange={(event) => setCommentDraft(event.currentTarget.value)}
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
    </div>
  )
}

export function ThreadReviewPane({
  batchLabel,
  items,
  stackKind = 'date_source',
  canReviewActions,
  dataOwnerPersona = false,
  onPromoteAll,
  onDeclineAll,
  onEscalateAll,
  actionPending,
  onBackToQueue,
  onSeeMoreDetails,
  assigneeCandidates = [],
  onBulkAssign,
}: {
  batchLabel: string
  items: NeedsAttentionItem[]
  stackKind?: InboxStackKind
  canReviewActions: boolean
  dataOwnerPersona?: boolean
  onPromoteAll: (responseStatus: DropResponseStatusCode) => void
  onDeclineAll: () => void
  onEscalateAll?: () => void
  actionPending: boolean
  onBackToQueue?: () => void
  onOpenDetail?: (item: NeedsAttentionItem, trigger: HTMLElement) => void
  onSeeMoreDetails?: () => void
  assigneeCandidates?: string[]
  onBulkAssign?: (target: AssignTarget) => void
}) {
  const [confirm, setConfirm] = useState<'fulfill' | 'decline' | 'escalate' | null>(null)
  const [tab, setTab] = useState<InboxWorkbenchTab>(() =>
    items.some(isMatchingItem) ? 'matching' : 'overview',
  )
  useEffect(() => {
    setTab(items.some(isMatchingItem) ? 'matching' : 'overview')
  }, [batchLabel, stackKind])
  const threadFulfillSuggestion = suggestedBulkFulfillStatus(items)
  const [fulfillStatus, setFulfillStatus] = useState<DropResponseStatusCode | null>(
    threadFulfillSuggestion,
  )
  const wasActionPending = useRef(false)
  useEffect(() => {
    if (wasActionPending.current && !actionPending) setConfirm(null)
    wasActionPending.current = actionPending
  }, [actionPending])
  const earliest = items.reduce<NeedsAttentionItem | null>((best, item) => {
    if (!best) return item
    return (item.requested_at ?? '') < (best.requested_at ?? '') ? item : best
  }, null)
  const showDisposition = canReviewActions && onPromoteAll != null && onDeclineAll != null
  const memberCount = items.length
  const matchingStatus = stackMatchingStatusSummary(items, dataOwnerPersona)
  const sharedAssignee = items.every(
    (item) =>
      (item.assignment?.assignee_identity ?? null) ===
      (items[0]?.assignment?.assignee_identity ?? null),
  )
    ? items[0]?.assignment?.assignee_identity
    : null
  const sharedGroup = items.every(
    (item) =>
      (item.assignment?.target_role ?? null) === (items[0]?.assignment?.target_role ?? null),
  )
    ? items[0]?.assignment?.target_role === 'legal'
      ? 'legal'
      : items[0]?.assignment?.target_role === 'data'
        ? 'data'
        : null
    : null

  const bulkId =
    stackKind === 'date_source' ||
    stackKind === 'batch_type' ||
    stackKind === 'batch_status'
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

  const stackChrome = useMemo(() => aggregateStackWorkbenchChrome(items), [items])
  const batchWorkbench = batchWorkbenchQuery.data
  const pipelineStages = stackChrome.stages
  const matchingCluster = batchWorkbench
    ? batchClusterAsPipelineRows(batchWorkbench.matching_cluster)
    : undefined
  const fulfillmentCluster = batchWorkbench
    ? batchClusterAsPipelineRows(batchWorkbench.fulfillment_cluster)
    : undefined
  const pipelineSubsteps = useMemo(
    () =>
      dataOwnerPersona
        ? aggregateOwnerSystemWorkbenchSubsteps(items)
        : [
            ...stackChrome.substeps,
            ...batchClusterAsSubsteps(batchWorkbench?.matching_cluster, 'matching'),
            ...batchClusterAsSubsteps(batchWorkbench?.fulfillment_cluster, 'fulfillment'),
          ],
    [
      batchWorkbench?.fulfillment_cluster,
      batchWorkbench?.matching_cluster,
      dataOwnerPersona,
      items,
      stackChrome.substeps,
    ],
  )
  const stackCountCaption = inboxStackCountCaption(stackChrome.member_count)
  const { me } = useMe()
  const threadConnectorBlock = inboxItemsConnectorBlock(items, {
    reminders: me?.connector_reminders,
  })

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
      <ConfirmActionDialog
        open={confirm === 'fulfill'}
        onOpenChange={(open) => {
          if (!open && !actionPending) setConfirm(null)
          if (open) setFulfillStatus(threadFulfillSuggestion)
        }}
        title={
          dataOwnerPersona
            ? `Confirm ${memberCount} match${memberCount === 1 ? '' : 'es'}?`
            : `Fulfill ${memberCount} request${memberCount === 1 ? '' : 's'}?`
        }
        description={
          dataOwnerPersona
            ? `Confirm the match result for ${memberCount} request${memberCount === 1 ? '' : 's'} in this group.`
            : `Approve matching review for ${memberCount} request${memberCount === 1 ? '' : 's'} in this group and set the CA DROP status result.`
        }
        confirmLabel={
          dataOwnerPersona
            ? `Confirm ${memberCount}`
            : `Fulfill ${memberCount}`
        }
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
          suggested={threadFulfillSuggestion}
          persona={dataOwnerPersona ? 'data_owner' : 'ops'}
        />
      </ConfirmActionDialog>
      <ConfirmActionDialog
        open={confirm === 'decline'}
        onOpenChange={(open) => {
          if (!open && !actionPending) setConfirm(null)
        }}
        title={`Decline ${memberCount} request${memberCount === 1 ? '' : 's'}?`}
        description={`Decline ${memberCount} request${memberCount === 1 ? '' : 's'} in this group without fulfillment.`}
        confirmLabel={`Decline ${memberCount}`}
        tone="destructive"
        confirming={actionPending && confirm === 'decline'}
        onConfirm={() => onDeclineAll()}
      />
      <ConfirmActionDialog
        open={confirm === 'escalate'}
        onOpenChange={(open) => {
          if (!open && !actionPending) setConfirm(null)
        }}
        title="Assign to legal?"
        description={`Send ${memberCount} matching review${memberCount === 1 ? '' : 's'} in this batch to Legal Inbox for the request journey. Add a comment first if context is needed.`}
        confirmLabel="Assign to legal"
        confirming={actionPending && confirm === 'escalate'}
        onConfirm={() => onEscalateAll?.()}
      />

      <RequestDetailWorkbenchShell
        header={
      <div className="shrink-0 space-y-1.5 border-b border-line px-3 py-2">
        {onBackToQueue ? (
          <button
            type="button"
            onClick={onBackToQueue}
            className="mb-1 text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline md:hidden"
          >
            ← Queue
          </button>
        ) : null}
        <Micro>{inboxThreadMicroLabel(stackKind)}</Micro>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-ink">{batchLabel}</h2>
            <p className="text-[0.65rem] text-mute">
              {items.length} request{items.length === 1 ? '' : 's'}
              {earliest ? ` · ${formatDueLabel(earliest)}` : ''}
            </p>
            {threadConnectorBlock ? (
              <div className="mt-1.5">
                <InboxConnectorStatusChrome
                  block={threadConnectorBlock}
                  verticalId={items[0]?.vertical}
                  showWizard={dataOwnerPersona}
                />
              </div>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Badge
              variant={matchingStatus.mixed ? 'wait' : 'ok'}
              className="normal-case tracking-normal"
              aria-label={`Matching status ${matchingStatus.label}`}
            >
              {matchingStatus.label}
            </Badge>
            {onBulkAssign ? (
              <AssigneeAvatarPicker
                currentEmail={sharedAssignee}
                currentGroup={sharedGroup}
                candidates={assigneeCandidates}
                disabled={!canReviewActions}
                pending={actionPending}
                error={null}
                onAssign={onBulkAssign}
                ownerAssignMode={dataOwnerPersona}
              />
            ) : null}
          </div>
        </div>
        {showDisposition ? (
          <InboxMatchingDispositionCard
            variant="batch"
            canReviewActions={canReviewActions}
            actionPending={actionPending}
            dataOwnerPersona={dataOwnerPersona}
            onConfirm={() => setConfirm('fulfill')}
            onDecline={() => setConfirm('decline')}
            onEscalate={() => setConfirm('escalate')}
            onSeeMoreDetails={
              onSeeMoreDetails
                ? (_trigger) => onSeeMoreDetails()
                : undefined
            }
          />
        ) : null}
      </div>
        }
        rail={
          <ThinJourneyPipeline
            stages={pipelineStages}
            substeps={pipelineSubsteps}
            matchingCluster={matchingCluster}
            fulfillmentCluster={fulfillmentCluster}
            splitPosture={batchWorkbench?.split_posture ?? stackChrome.split_posture}
            density="compact"
            showSubsteps={false}
            expandedStage={isWorkbenchStageKey(tab) ? tab : null}
            onStageActivate={(stage) => {
              if (isWorkbenchStageKey(stage)) setTab(stage)
            }}
          />
        }
        side={
          earliest ? (
            <RequestDetailSideColumn
              activity={
                <InboxActivityPanel requestId={earliest.request_id} canCompose={false} />
              }
              comments={
                <InboxEarliestComments
                  requestId={earliest.request_id}
                  canCompose={canReviewActions}
                />
              }
            />
          ) : undefined
        }
      >
      <Tabs
        value={tab}
        onValueChange={(value) => {
          if (value === 'overview' || isWorkbenchStageKey(value)) {
            setTab(value)
          }
        }}
        className="flex min-h-0 flex-1 flex-col overflow-hidden"
      >
        <div className="shrink-0 border-b border-line px-3 py-1">
          <TabsList
            className="h-8 w-full justify-start gap-1 overflow-x-auto rounded-md border border-line bg-canvas p-0.5"
            aria-label="Thread detail sections"
          >
            <TabsTrigger value="overview" className={INBOX_DETAIL_TAB_TRIGGER}>
              Overview
            </TabsTrigger>
            <TabsTrigger value="ingest" className={INBOX_DETAIL_TAB_TRIGGER}>
              Ingest
            </TabsTrigger>
            <TabsTrigger value="matching" className={INBOX_DETAIL_TAB_TRIGGER}>
              Matching
            </TabsTrigger>
            <TabsTrigger value="fulfillment" className={INBOX_DETAIL_TAB_TRIGGER}>
              Fulfillment
            </TabsTrigger>
            <TabsTrigger value="notice" className={INBOX_DETAIL_TAB_TRIGGER}>
              Notice
            </TabsTrigger>
          </TabsList>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2.5">
          <TabsContent value="overview" className="mt-0 space-y-3">
            <p className="text-xs text-ink-soft">
              Collective stack summary. Open a queue row on the left to inspect one match.
            </p>
            <StackCollectiveSummary items={items} dataOwnerPersona={dataOwnerPersona} />
          </TabsContent>

          <TabsContent value="ingest" className="mt-0 space-y-3">
            <p className="text-[0.65rem] text-mute">{stackCountCaption}</p>
            <JourneyStageSubsteps
              stages={pipelineStages}
              stageKey="ingest"
              substeps={pipelineSubsteps}
              density="compact"
            />
          </TabsContent>

          <TabsContent value="matching" className="mt-0 space-y-3">
            <p className="text-[0.65rem] text-mute">{stackCountCaption}</p>
            <JourneyStageSubsteps
              stages={pipelineStages}
              stageKey="matching"
              substeps={pipelineSubsteps}
              density="compact"
            />
            <StackCollectiveSummary
              items={items}
              dataOwnerPersona={dataOwnerPersona}
              showMatching
            />
          </TabsContent>

          <TabsContent value="fulfillment" className="mt-0 space-y-3">
            <p className="text-[0.65rem] text-mute">{stackCountCaption}</p>
            <JourneyStageSubsteps
              stages={pipelineStages}
              stageKey="fulfillment"
              substeps={pipelineSubsteps}
              density="compact"
            />
          </TabsContent>

          <TabsContent value="notice" className="mt-0 space-y-3">
            <p className="text-[0.65rem] text-mute">{stackCountCaption}</p>
            <JourneyStageSubsteps
              stages={pipelineStages}
              stageKey="notice"
              substeps={pipelineSubsteps}
              density="compact"
            />
          </TabsContent>
        </div>
      </Tabs>
      </RequestDetailWorkbenchShell>
    </div>
  )
}

/** Shared Inbox queue chrome — live Inbox and Results lab must not fork this markup. */
export function InboxQueueRows({
  groupingActive,
  rows,
  selectedKeys,
  activeTarget,
  expandedThreads,
  dataOwnerPersona,
  legalPersona = false,
  connectorReminders = null,
  connectorGate = null,
  onToggleThreadSelect,
  onToggleThreadExpand,
  onOpenThread,
  onToggleItem,
  onOpenItem,
}: {
  groupingActive: boolean
  rows: InboxRow[]
  selectedKeys: Set<string>
  activeTarget: InboxActiveTarget | null
  expandedThreads: Set<string>
  dataOwnerPersona: boolean
  legalPersona?: boolean
  connectorReminders?: ConnectorReminder[] | null
  connectorGate?: MatchingConnectorGate | null
  onToggleThreadSelect: (ids: string[]) => void
  onToggleThreadExpand: (batchKey: string) => void
  onOpenThread: (batchKey: string) => void
  onToggleItem: (itemKey: string) => void
  onOpenItem: (itemKey: string) => void
}) {
  return (
    <TooltipProvider delayDuration={200}>
      {rows.map((row) => {
        if (row.kind === 'thread') {
          const ids = row.items.map((item) => inboxReviewItemKey(item))
          const selected = ids.every((id) => selectedKeys.has(id))
          const partial = !selected && ids.some((id) => selectedKeys.has(id))
          const active =
            activeTarget?.kind === 'thread' && activeTarget.batchKey === row.batchKey
          const expanded = expandedThreads.has(row.batchKey)
          const earliest = row.items[0]!
          const exactMatchBatch =
            (row.stackKind === 'date_source' ||
              row.stackKind === 'batch_type' ||
              row.stackKind === 'batch_status') &&
            threadIsExactMatchBatch(row.items)
          const isSystemStack = row.stackKind === 'system'
          const isCrossStack = row.stackKind === 'batch_type'
          const isStatusStack = row.stackKind === 'status'
          const isBatchStatusStack = row.stackKind === 'batch_status'
          const statusSubtitle = inboxBatchStatusStackSubtitle(row.items, dataOwnerPersona)
          const threadConnectorBlock = inboxItemsConnectorBlock(row.items, {
            reminders: connectorReminders,
            gate: connectorGate,
          })
          const stackKindLabel = isBatchStatusStack
            ? 'date · status'
            : isCrossStack
              ? 'date · system'
              : isStatusStack
                ? 'status'
                : isSystemStack
                  ? 'system'
                  : 'date · source'
          return (
            <li key={`thread-${row.batchKey}`} className="list-none">
              <div
                className={cn(
                  'relative flex min-h-0 items-stretch gap-0 border-b border-line/80 bg-paper',
                  active
                    ? 'bg-habeas-navy/[0.07]'
                    : selected
                      ? 'bg-habeas-navy/[0.03]'
                      : 'hover:bg-panel/40',
                )}
              >
                <span
                  className={cn(
                    'w-0.5 shrink-0 self-stretch',
                    isCrossStack || isBatchStatusStack
                      ? 'bg-habeas-navy/80'
                      : isSystemStack || isStatusStack
                        ? 'bg-habeas-navy/45'
                        : 'bg-habeas-navy/70',
                  )}
                  aria-hidden
                />
                <label
                  className="flex shrink-0 cursor-pointer items-center px-1"
                  onClick={(event) => event.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    className="h-3 w-3 rounded border-line accent-habeas-navy"
                    checked={selected}
                    ref={(element) => {
                      if (element) element.indeterminate = partial
                    }}
                    onChange={() => onToggleThreadSelect(ids)}
                    aria-label={`Select ${stackKindLabel} ${row.batchLabel}`}
                  />
                </label>
                <button
                  type="button"
                  className="shrink-0 self-center rounded px-0.5 py-0.5 text-xs leading-normal text-mute hover:bg-panel hover:text-ink"
                  aria-label={
                    expanded
                      ? `Collapse ${row.batchLabel}`
                      : `Expand ${row.batchLabel}`
                  }
                  onClick={() => onToggleThreadExpand(row.batchKey)}
                >
                  {expanded ? '▾' : '▸'}
                </button>
                <button
                  type="button"
                  onClick={() => onOpenThread(row.batchKey)}
                  className={INBOX_QUEUE_ROW_BUTTON}
                  aria-label={`${row.batchLabel}, ${row.items.length} requests`}
                >
                  <InboxCountHint count={row.items.length} />
                  <span className="min-w-0 truncate font-medium text-ink">
                    {row.batchLabel}
                  </span>
                  {statusSubtitle || exactMatchBatch ? (
                    <InboxMatchHint
                      matchType={
                        exactMatchBatch
                          ? 'single_match'
                          : inboxMatchHintKind(null, statusSubtitle)
                      }
                      dataOwnerPersona={dataOwnerPersona}
                      label={statusSubtitle ?? 'Exact 1:1'}
                    />
                  ) : null}
                  <InboxConnectorStatusHint block={threadConnectorBlock} />
                  <InboxDueHint item={earliest} />
                </button>
              </div>
              {expanded ? (
                <ul className="mx-0.5 mb-0 space-y-0 overflow-hidden rounded-sm border border-habeas-navy/15 border-t-0 bg-canvas/50 py-0">
                  {row.items.map((item) => {
                    const itemKey = inboxReviewItemKey(item)
                    const verticalLabelText = inboxReviewItemVerticalLabel(item)
                    const systemLabelText = inboxReviewItemSystemLabel({
                      request_id: item.request_id,
                      system: inboxItemSystemId(item),
                      system_label: item.system_label,
                      vertical: item.vertical,
                    })
                    const childSelected = selectedKeys.has(itemKey)
                    const childActive =
                      activeTarget?.kind === 'request' && activeTarget.itemKey === itemKey
                    const railClass = inboxSystemRailClass(item.color_token)
                    return (
                      <li key={itemKey}>
                        <div
                          className={cn(
                            'flex items-stretch gap-0 pl-6 transition-colors',
                            railClass && 'border-l-2',
                            railClass,
                            childActive
                              ? 'bg-habeas-navy/[0.07]'
                              : childSelected
                                ? 'bg-habeas-navy/[0.03]'
                                : 'hover:bg-panel/40',
                          )}
                        >
                          <label
                            className="flex shrink-0 cursor-pointer items-center px-1"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <input
                              type="checkbox"
                              className="h-3 w-3 rounded border-line accent-habeas-navy"
                              checked={childSelected}
                              onChange={() => onToggleItem(itemKey)}
                              aria-label={
                                systemLabelText
                                  ? `Select ${systemLabelText} matching result`
                                  : verticalLabelText
                                    ? `Select ${verticalLabelText} matching result`
                                    : `Select ${item.request_id}`
                              }
                            />
                          </label>
                          <button
                            type="button"
                            onClick={() => onOpenItem(itemKey)}
                            className={INBOX_QUEUE_ROW_BUTTON}
                          >
                            {item.color_token ? (
                              <span
                                className={cn(
                                  'h-1.5 w-1.5 shrink-0 rounded-full border',
                                  matchingSystemColorClass(item.color_token),
                                )}
                                aria-hidden
                              />
                            ) : null}
                            <span
                              className={cn(
                                'truncate font-medium',
                                inboxSystemTitleClass(item.color_token),
                              )}
                            >
                              {inboxItemTitle(item)}
                            </span>
                            {verticalLabelText ? (
                              <InboxVerticalHint label={verticalLabelText} />
                            ) : null}
                            <InboxConnectorStatusHint
                              block={inboxItemConnectorBlock(item, {
                                reminders: connectorReminders,
                                gate: connectorGate,
                              })}
                            />
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

        if (groupingActive) return null

        const item = row.item
        const itemKey = inboxReviewItemKey(item)
        const verticalLabelText = inboxReviewItemVerticalLabel(item)
        const systemLabelText = inboxReviewItemSystemLabel({
          request_id: item.request_id,
          system: inboxItemSystemId(item),
          system_label: item.system_label,
          vertical: item.vertical,
        })
        const selected = selectedKeys.has(itemKey)
        const active = activeTarget?.kind === 'request' && activeTarget.itemKey === itemKey
        const urgentAssignment = legalPersona && isAssignmentToLegalItem(item)
        const railClass = inboxSystemRailClass(item.color_token)
        return (
          <li key={itemKey}>
            <div
              className={cn(
                'flex items-stretch gap-0 transition-colors',
                urgentAssignment && 'border-l-2 border-l-red-600',
                !urgentAssignment && railClass && 'border-l-2',
                !urgentAssignment && railClass,
                active
                  ? 'bg-habeas-navy/[0.07]'
                  : selected
                    ? 'bg-habeas-navy/[0.03]'
                    : 'hover:bg-panel/50',
              )}
            >
              <label
                className="flex shrink-0 cursor-pointer items-center px-1"
                onClick={(event) => event.stopPropagation()}
              >
                <input
                  type="checkbox"
                  className="h-3 w-3 rounded border-line accent-habeas-navy"
                  checked={selected}
                  onChange={() => onToggleItem(itemKey)}
                  aria-label={
                    systemLabelText
                      ? `Select ${systemLabelText} matching result`
                      : verticalLabelText
                        ? `Select ${verticalLabelText} matching result`
                        : `Select ${item.request_id}`
                  }
                />
              </label>
              <button
                type="button"
                onClick={() => onOpenItem(itemKey)}
                className={INBOX_QUEUE_ROW_BUTTON}
              >
                {item.color_token ? (
                  <span
                    className={cn(
                      'h-1.5 w-1.5 shrink-0 rounded-full border',
                      matchingSystemColorClass(item.color_token),
                    )}
                    aria-hidden
                  />
                ) : null}
                <span
                  className={cn(
                    'min-w-0 truncate font-medium',
                    inboxSystemTitleClass(item.color_token),
                  )}
                >
                  {inboxItemTitle(item)}
                </span>
                {urgentAssignment ? (
                  <InboxHintGlyph
                    label="Urgent"
                    className="rounded-sm bg-red-50 text-red-700"
                  >
                    <span className="text-[0.7rem] font-bold leading-none">!</span>
                  </InboxHintGlyph>
                ) : null}
                {item.match_type ? (
                  <InboxMatchHint
                    matchType={item.match_type}
                    dataOwnerPersona={dataOwnerPersona}
                  />
                ) : null}
                <InboxConnectorStatusHint
                  block={inboxItemConnectorBlock(item, {
                    reminders: connectorReminders,
                    gate: connectorGate,
                  })}
                />
                {verticalLabelText ? (
                  <InboxVerticalHint label={verticalLabelText} />
                ) : null}
                <InboxDueHint item={item} />
              </button>
            </div>
          </li>
        )
      })}
    </TooltipProvider>
  )
}

export function NeedsAttentionPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const search = useSearch({ from: '/requests/needs-attention' })
  const bulkFilter = search.bulk
  const { isAdmin, role, me, isLoading: meLoading } = useMe()
  const legalPersona = isLegalAdminPersona(role)
  const dataOwnerPersona = isVerticalOperatorRole(role)
  const canReviewActions =
    Boolean(isAdmin) || legalPersona || dataOwnerPersona
  const inboxConnectorGate = useMatchingConnectorGate({
    reminders: me?.connector_reminders,
    fetchConnections: Boolean(isAdmin),
  })
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
  const inboxConnectorNotifGroups = useMemo(
    () =>
      groupInboxConnectorNotifications({
        reminders: me?.connector_reminders,
        gate: inboxConnectorGate,
      }),
    [me?.connector_reminders, inboxConnectorGate],
  )
  const showInboxConnectorNotifications =
    inboxConnectorNotifGroups.length > 0 &&
    !legalPersona &&
    (inboxKind === 'matching' || inboxKind === 'all')
  const [matchFilter, setMatchFilter] = useState<MatchFilter>('all')
  const [dueFilter, setDueFilter] = useState<DueFilter>('all')
  /** null → persona default (legal: off, ops/matching: on). */
  const [groupByBatchOverride, setGroupByBatchOverride] = useState<boolean | null>(
    null,
  )
  const groupByBatch = groupByBatchOverride ?? !legalPersona
  const [groupBySystem, setGroupBySystem] = useState(false)
  const [groupByStatus, setGroupByStatus] = useState(false)
  const [page, setPage] = useState(1)
  const listChrome = useInboxListCollapsed()

  useEffect(() => {
    // Collapsed groups when grouping mode changes — avoids “stuck” expanded flat-looking lists.
    setExpandedThreads(new Set())
  }, [groupByBatch, groupBySystem, groupByStatus])

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

  const ownerFulfillmentQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      'needs-attention',
      'data-owner',
      'fulfillment',
      inboxFetchLimit,
    ],
    queryFn: () => getOwnerFulfillmentNeedsAttention({ limit: inboxFetchLimit }),
    enabled: dataOwnerPersona,
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const ownerMatchingQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      'needs-attention',
      'data-owner',
      'matching',
      inboxFetchLimit,
      search.vertical ?? null,
      search.system ?? null,
    ],
    queryFn: () =>
      getOwnerMatchingNeedsAttention({
        limit: inboxFetchLimit,
        offset: 0,
        vertical: search.vertical,
        system: search.system,
      }),
    enabled: dataOwnerPersona,
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const attentionQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      'needs-attention',
      legalPersona ? 'legal' : 'ops',
      search.assignee ?? null,
      inboxFetchLimit,
      search.vertical ?? null,
      search.system ?? null,
    ],
    queryFn: () => {
      if (search.assignee) {
        return getNeedsAttention({
          limit: inboxFetchLimit,
          offset: 0,
          kind: 'matching',
          assignee: search.assignee,
          vertical: search.vertical,
          system: search.system,
        })
      }
      if (legalPersona) {
        return getLegalNeedsAttention({ limit: inboxFetchLimit, offset: 0 })
      }
      return getNeedsAttention({
        limit: inboxFetchLimit,
        offset: 0,
        vertical: search.vertical,
        system: search.system,
      })
    },
    enabled: !dataOwnerPersona,
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const verticalFilter = search.vertical?.trim() || undefined
  const systemFilter = search.system?.trim() || undefined
  const sourceFilter = search.source?.trim() || undefined
  const stepFilter = search.step || undefined

  function patchInboxCatalogSearch(
    patch: Partial<Pick<InboxCatalogSearch, 'vertical' | 'system' | 'source' | 'step'>>,
  ) {
    void navigate({
      to: '/requests/needs-attention',
      search: (prev) => mergeInboxCatalogSearch(prev, patch),
      replace: true,
    })
  }

  function setLegalFilterAndUrl(next: LegalInboxFilter | null) {
    setLegalInboxFilter(next)
    setMobilePane('queue')
    void navigate({
      to: '/requests/needs-attention',
      search: (prev) =>
        mergeInboxCatalogSearch(prev, { filter: next ?? undefined }),
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
      search: (prev) =>
        mergeInboxCatalogSearch(prev, {
          kind: next === defaultKind && !legalPersona ? undefined : next,
        }),
      replace: true,
    })
  }

  const ownerTaskItems = useMemo(() => {
    if (!dataOwnerPersona) return []
    const matching = ownerMatchingQuery.data?.items ?? []
    const fulfillment = ownerFulfillmentQuery.data?.items ?? []
    return [...matching, ...fulfillment].filter((item) =>
      isOwnerVerticalTask(item, me?.verticals),
    )
  }, [
    dataOwnerPersona,
    me?.verticals,
    ownerFulfillmentQuery.data?.items,
    ownerMatchingQuery.data?.items,
  ])

  const rawItems =
    dataOwnerPersona && inboxKind === 'fulfillment'
      ? (ownerFulfillmentQuery.data?.items ?? [])
      : dataOwnerPersona && inboxKind === 'pending_tasks'
        ? ownerTaskItems
        : dataOwnerPersona
          ? (ownerMatchingQuery.data?.items ?? [])
          : (attentionQuery.data?.items ?? [])
  const items = useMemo(() => {
    const scoped = dataOwnerPersona
      ? ownerVisibleInboxItems(rawItems, me?.verticals)
      : rawItems
    const normalized = scoped.map(normalizeInboxItem)
    return coalesceInboxReviewItems(
      dataOwnerPersona ? expandInboxReviewBySystem(normalized) : normalized,
    )
  }, [dataOwnerPersona, me?.verticals, rawItems])
  const ownerFulfillmentCount =
    ownerFulfillmentQuery.data?.total ?? ownerFulfillmentQuery.data?.items.length ?? 0
  const ownerMatchingCount =
    ownerMatchingQuery.data?.total ?? ownerMatchingQuery.data?.items.length ?? 0
  const ownerAssignedCount = ownerTaskItems.length
  const attentionListQuery =
    dataOwnerPersona && inboxKind === 'fulfillment'
      ? ownerFulfillmentQuery
      : dataOwnerPersona && inboxKind === 'pending_tasks'
        ? ownerMatchingQuery
        : dataOwnerPersona
          ? ownerMatchingQuery
          : attentionQuery

  const operatorsQuery = useQuery({
    queryKey: ['admin-api', 'legal', 'operators'],
    queryFn: getLegalOperators,
    enabled: Boolean(isAdmin || legalPersona || dataOwnerPersona),
    staleTime: 60_000,
  })
  const ownerVerticalIds = me?.verticals ?? []
  const verticalMembersQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'vertical-members', ownerVerticalIds],
    queryFn: async () => {
      const rows = await Promise.all(
        ownerVerticalIds.filter(Boolean).map((id) => listVerticalMembers(id)),
      )
      return rows.flat()
    },
    enabled: Boolean(dataOwnerPersona && ownerVerticalIds.length > 0),
    staleTime: 60_000,
  })

  const assigneeCandidates = useMemo(
    () =>
      resolveInboxAssignCandidates({
        dataOwnerPersona,
        selfEmail: me?.email,
        itemAssigneeEmails: items
          .map((item) => item.assignment?.assignee_identity?.trim())
          .filter((email): email is string => Boolean(email)),
        verticalMemberEmails: (verticalMembersQuery.data ?? [])
          .filter((row) => row.active !== false)
          .map((row) => row.email),
        operators: operatorsQuery.data ?? [],
      }),
    [
      dataOwnerPersona,
      items,
      me?.email,
      operatorsQuery.data,
      verticalMembersQuery.data,
    ],
  )

  const kindCounts = useMemo(() => {
    const myEmail = me?.email
    let matching = 0
    let triage = 0
    let escalations = 0
    let delivery = 0
    let notice = 0
    let communications = 0
    let fulfillment = 0
    let pendingTasks = 0
    for (const item of items) {
      if (isMatchingItem(item)) matching += 1
      if (isTriageItem(item)) triage += 1
      if (isEscalationItem(item)) escalations += 1
      if (isDeliveryItem(item)) delivery += 1
      if (isNoticeItem(item)) notice += 1
      if (isCommsItem(item)) communications += 1
      if (isOwnerFulfillmentItem(item)) fulfillment += 1
      if (dataOwnerPersona) {
        if (isOwnerVerticalTask(item, me?.verticals)) pendingTasks += 1
      } else if (isPendingTaskFor(item, myEmail)) {
        pendingTasks += 1
      }
    }
    return {
      all: items.length,
      matching: dataOwnerPersona ? ownerMatchingCount : matching,
      triage,
      escalations,
      delivery,
      notice,
      communications,
      fulfillment: dataOwnerPersona ? ownerFulfillmentCount : fulfillment,
      pending_tasks: dataOwnerPersona ? ownerAssignedCount : pendingTasks,
    } satisfies Record<InboxKind, number>
  }, [
    dataOwnerPersona,
    items,
    me?.email,
    me?.verticals,
    ownerAssignedCount,
    ownerFulfillmentCount,
    ownerMatchingCount,
  ])

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

  const catalogFilterPayload = dataOwnerPersona
    ? ownerMatchingQuery.data
    : attentionQuery.data
  const verticalFilterOptions = useMemo(() => {
    if (dataOwnerPersona) {
      const assigned = (me?.assigned_vertical_labels ?? []).map((row) => ({
        id: row.vertical_id,
        label: row.display_label,
      }))
      if (assigned.length > 0) return assigned
    }
    const fromApi = catalogFilterPayload?.filter_verticals ?? []
    return fromApi.length > 0 ? fromApi : catalogOptionsFromItems(items, 'vertical')
  }, [
    catalogFilterPayload?.filter_verticals,
    dataOwnerPersona,
    items,
    me?.assigned_vertical_labels,
  ])
  const systemFilterOptions = useMemo(() => {
    const fromApi = catalogFilterPayload?.filter_systems ?? []
    const options = fromApi.length > 0 ? fromApi : catalogOptionsFromItems(items, 'system')
    return inboxSystemFilterOptions(options, verticalFilter)
  }, [catalogFilterPayload?.filter_systems, items, verticalFilter])
  const showSystem = useMemo(() => {
    const unique = new Set(
      systemFilterOptions.map((row) => row.id.trim()).filter(Boolean),
    )
    return unique.size >= 2
  }, [systemFilterOptions])
  const effectiveGroupBySystem = showSystem && groupBySystem
  const groupingActive = groupByBatch || effectiveGroupBySystem || groupByStatus

  const sourceOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const item of items) {
      for (const id of inboxItemSourceIds(item)) {
        counts.set(id, (counts.get(id) ?? 0) + 1)
      }
    }
    const extras = [...counts.keys()].filter(
      (id) =>
        !(INBOX_INTAKE_SOURCE_ORDER as readonly string[]).includes(id) &&
        !isInboxIdentifierSurface(id),
    )
    const ordered = [
      ...INBOX_INTAKE_SOURCE_ORDER.filter((id) => counts.has(id)),
      ...extras.sort((left, right) => left.localeCompare(right)),
    ]
    return ordered.map((id) => ({
      id,
      label: inboxItemSourceLabel(id),
      count: counts.get(id) ?? 0,
    }))
  }, [items])

  const stepOptions = useMemo(() => {
    const counts = new Map<WorkbenchStageKey, number>()
    for (const item of items) {
      const step = inboxItemStep(item)
      counts.set(step, (counts.get(step) ?? 0) + 1)
    }
    return INBOX_STEP_KEYS.filter((id) => (counts.get(id) ?? 0) > 0).map((id) => ({
      id,
      label:
        id === 'ingest'
          ? 'Ingest'
          : id === 'matching'
            ? 'Matching'
            : id === 'fulfillment'
              ? 'Fulfillment'
              : 'Notice',
      count: counts.get(id) ?? 0,
    }))
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
        if (inboxKind === 'fulfillment' && !isOwnerFulfillmentItem(item)) return false
        if (inboxKind === 'pending_tasks') {
          if (dataOwnerPersona) {
            if (!isOwnerVerticalTask(item, me?.verticals)) return false
          } else if (!isPendingTaskFor(item, myEmail)) {
            return false
          }
        }
        if (inboxKind === 'matching' || inboxKind === 'all') {
          if (matchFilter !== 'all') {
            const key = (item.match_type as MatchFilter | undefined) ?? 'unknown'
            if (key !== matchFilter) return false
          }
        }
      }
      if (dueFilter !== 'all' && dueBucket(item) !== dueFilter) return false
      if (verticalFilter && item.vertical?.trim() !== verticalFilter) return false
      if (showSystem && systemFilter && !inboxItemHasSystem(item, systemFilter)) {
        return false
      }
      if (
        sourceFilter &&
        !isInboxIdentifierSurface(sourceFilter) &&
        !inboxItemSourceIds(item).includes(sourceFilter)
      ) {
        return false
      }
      if (stepFilter && inboxItemStep(item) !== stepFilter) return false
      return true
    })
  }, [
    items,
    inboxKind,
    legalInboxFilter,
    legalPersona,
    dataOwnerPersona,
    matchFilter,
    dueFilter,
    me?.email,
    me?.verticals,
    bulkFilter,
    showMatchResultFilters,
    verticalFilter,
    systemFilter,
    showSystem,
    sourceFilter,
    stepFilter,
  ])

  const inboxRows = useMemo(
    () =>
      coerceGroupedInboxRows(
        buildGroupedInboxRows(
          filteredItems,
          {
            byDateSource: groupByBatch,
            bySystem: effectiveGroupBySystem,
            byStatus: groupByStatus,
            reminders: me?.connector_reminders,
            gate: inboxConnectorGate,
          },
          dataOwnerPersona,
        ),
        groupingActive,
      ),
    [
      filteredItems,
      groupByBatch,
      effectiveGroupBySystem,
      groupByStatus,
      groupingActive,
      dataOwnerPersona,
    ],
  )

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
    groupBySystem,
    groupByStatus,
    bulkFilter,
    search.assignee,
    verticalFilter,
    systemFilter,
    sourceFilter,
    stepFilter,
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
  const rawInboxTotal = attentionListQuery.data?.total ?? items.length
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
        : filteredItems.some(
            (item) => inboxReviewItemKey(item) === activeTarget.itemKey,
          ))
    if (!stillValid) {
      const pick = firstIndividualInboxTarget(inboxRows)
      if (!pick) {
        setActiveTarget(null)
        return
      }
      if (pick.expandBatchKey) {
        setExpandedThreads((previous) => {
          if (previous.has(pick.expandBatchKey!)) return previous
          const next = new Set(previous)
          next.add(pick.expandBatchKey!)
          return next
        })
      }
      setActiveTarget(pick.target)
    }
  }, [inboxRows, filteredItems, activeTarget])

  const activeThread =
    activeTarget?.kind === 'thread'
      ? findThreadRow(inboxRows, activeTarget.batchKey)
      : null

  const activeItem =
    activeTarget?.kind === 'request'
      ? (filteredItems.find(
          (item) => inboxReviewItemKey(item) === activeTarget.itemKey,
        ) ?? null)
      : null

  const filteredIds = useMemo(
    () => filteredItems.map((item) => inboxReviewItemKey(item)),
    [filteredItems],
  )

  const allFilteredSelected =
    filteredIds.length > 0 && filteredIds.every((id) => selectedIds.has(id))
  const someFilteredSelected = filteredIds.some((id) => selectedIds.has(id))

  const bulkFulfillTargets = allFilteredSelected
    ? filteredItems
    : filteredItems.filter((item) => selectedIds.has(inboxReviewItemKey(item)))
  const bulkFulfillSuggestion = suggestedBulkFulfillStatus(bulkFulfillTargets)
  const [bulkFulfillStatus, setBulkFulfillStatus] =
    useState<DropResponseStatusCode | null>(null)
  const [bulkSelectedDwids, setBulkSelectedDwids] = useState<string[]>([])

  const bulkFulfillTargetIds = useMemo(() => {
    if (bulkConfirm !== 'fulfill') return []
    const items = allFilteredSelected
      ? filteredItems
      : filteredItems.filter((item) => selectedIds.has(inboxReviewItemKey(item)))
    return [...new Set(items.map((item) => item.request_id))].filter(isRequestUuid)
  }, [bulkConfirm, allFilteredSelected, filteredItems, selectedIds])

  const singleNeedsAttentionBulkId =
    bulkFulfillTargetIds.length === 1 ? bulkFulfillTargetIds[0] : null
  const singleNeedsAttentionBulkVertical = useMemo(() => {
    if (!dataOwnerPersona || !singleNeedsAttentionBulkId) return null
    const selected = (
      allFilteredSelected
        ? filteredItems
        : filteredItems.filter((item) => selectedIds.has(inboxReviewItemKey(item)))
    ).find((item) => item.request_id === singleNeedsAttentionBulkId)
    return selected?.vertical?.trim() || null
  }, [
    allFilteredSelected,
    dataOwnerPersona,
    filteredItems,
    selectedIds,
    singleNeedsAttentionBulkId,
  ])

  const singleNeedsAttentionBulkSystem = useMemo(() => {
    if (!dataOwnerPersona || !singleNeedsAttentionBulkId) return null
    const selected = (
      allFilteredSelected
        ? filteredItems
        : filteredItems.filter((item) => selectedIds.has(inboxReviewItemKey(item)))
    ).find((item) => item.request_id === singleNeedsAttentionBulkId)
    return selected ? inboxItemSystemId(selected) : null
  }, [
    allFilteredSelected,
    dataOwnerPersona,
    filteredItems,
    selectedIds,
    singleNeedsAttentionBulkId,
  ])

  const singleNeedsAttentionBulkMatchingQuery = useQuery({
    queryKey: singleNeedsAttentionBulkVertical
      ? [
          'admin-api',
          'ops',
          'requests',
          singleNeedsAttentionBulkId,
          'verticals',
          singleNeedsAttentionBulkVertical,
          singleNeedsAttentionBulkSystem,
          'matching-results',
        ]
      : [
          'admin-api',
          'ops',
          'drop',
          'matching-results',
          'needs-attention-bulk',
          singleNeedsAttentionBulkId,
        ],
    queryFn: () =>
      singleNeedsAttentionBulkVertical && singleNeedsAttentionBulkId
        ? fetchOwnerVerticalMatchingDetailOptional(
            singleNeedsAttentionBulkId,
            singleNeedsAttentionBulkVertical,
            singleNeedsAttentionBulkSystem ?? undefined,
          )
        : fetchMatchingDetailOptional(singleNeedsAttentionBulkId!),
    enabled: Boolean(
      dataOwnerPersona &&
        bulkConfirm === 'fulfill' &&
        singleNeedsAttentionBulkId &&
        singleNeedsAttentionBulkVertical,
    ),
  })

  const bulkFulfillContacts =
    singleNeedsAttentionBulkMatchingQuery.data?.matched_contacts ?? []
  const bulkFulfillSuggestedStatus = useMemo(
    () =>
      singleNeedsAttentionBulkId && singleNeedsAttentionBulkMatchingQuery.data
        ? suggestedDropResponseStatus(
            singleNeedsAttentionBulkMatchingQuery.data.match_type,
            singleNeedsAttentionBulkMatchingQuery.data.match_count,
          )
        : bulkFulfillSuggestion,
    [
      singleNeedsAttentionBulkId,
      singleNeedsAttentionBulkMatchingQuery.data,
      bulkFulfillSuggestion,
    ],
  )

  useEffect(() => {
    if (bulkConfirm !== 'fulfill' || !dataOwnerPersona || !singleNeedsAttentionBulkId) return
    const nextStatus = bulkFulfillSuggestedStatus
    if (nextStatus == null) return
    setBulkFulfillStatus(nextStatus)
    const dwids = bulkFulfillContacts.map((contact) => contact.dwid)
    setBulkSelectedDwids(nextStatus === 3 || nextStatus === 4 ? dwids : [])
  }, [
    bulkConfirm,
    dataOwnerPersona,
    singleNeedsAttentionBulkId,
    bulkFulfillSuggestedStatus,
    bulkFulfillContacts,
  ])

  const bulkFulfillNeedsDwids = bulkFulfillStatus === 3 || bulkFulfillStatus === 4
  const bulkFulfillDwidsReady =
    !bulkFulfillNeedsDwids ||
    bulkSelectedDwids.length > 0 ||
    !dataOwnerPersona ||
    bulkFulfillTargetIds.length !== 1

  function handleBulkFulfillStatusChange(code: DropResponseStatusCode) {
    setBulkFulfillStatus(code)
    if (code === 5) {
      setBulkSelectedDwids([])
      return
    }
    if (code === 3 || code === 4) {
      setBulkSelectedDwids(bulkFulfillContacts.map((contact) => contact.dwid))
    }
  }

  const bulkMutation = useMutation({
    mutationFn: async ({
      action,
      requestIds,
      responseStatus,
      targets,
    }: {
      action: 'fulfill' | 'decline'
      requestIds: string[]
      responseStatus?: DropResponseStatusCode
      targets?: Array<{ request_id: string; vertical?: string | null; system?: string | null }>
    }) => {
      const promoteTargets =
        targets && targets.length > 0
          ? targets.filter((target) => isRequestUuid(target.request_id))
          : requestIds.map((request_id) => ({
              request_id,
              vertical: null as string | null,
              system: null as string | null,
            }))
      const results = await Promise.allSettled(
        promoteTargets.map(async (target) => {
          const vertical = target.vertical?.trim() || undefined
          const system = target.system?.trim() || undefined
          if (action !== 'fulfill') {
            return postDropMatchingResultDecline(target.request_id, { vertical, system })
          }
          if (dataOwnerPersona) {
            const dwids =
              promoteTargets.length === 1
                ? bulkSelectedDwids
                : vertical
                  ? await resolveOwnerPromoteDwids(
                      target.request_id,
                      vertical,
                      system,
                      responseStatus,
                    )
                  : undefined
            return postDropMatchingResultPromote(target.request_id, {
              response_status: responseStatus,
              ...promoteDwidsForStatus(responseStatus, dwids),
              vertical,
              system,
            })
          }
          const dwids = await resolvePromoteDwids(target.request_id, responseStatus)
          return postDropMatchingResultPromote(target.request_id, {
            response_status: responseStatus,
            ...promoteDwidsForStatus(responseStatus, dwids),
            vertical,
            system,
          })
        }),
      )
      const failedResults = results.filter(
        (result): result is PromiseRejectedResult => result.status === 'rejected',
      )
      const failed = failedResults.length
      const succeeded = results.length - failed
      const decisions = results.flatMap((result) =>
        result.status === 'fulfilled' ? [result.value] : [],
      )
      return { succeeded, failed, action, decisions }
    },
    onSuccess: async (result, variables) => {
      if (result.failed > 0) {
        actionToast.warning({
          title:
            result.action === 'fulfill'
              ? 'Bulk confirm partially completed'
              : 'Bulk decline partially completed',
          description: `${result.succeeded} recorded, ${result.failed} failed`,
          action: {
            label: 'Retry',
            onClick: () => bulkMutation.mutate(variables),
          },
        })
      } else if (result.action === 'fulfill') {
        const copy = matchingReviewBulkPromoteToast(result.decisions)
        actionToast.success({
          title: copy.title,
          description: copy.description,
        })
      } else {
        actionToast.success({
          title: 'Matching reviews declined',
          description: `${result.succeeded} declined`,
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

  const bulkEscalateMutation = useMutation({
    mutationFn: (requestIds: string[]) => {
      const validIds = filterRequestUuids(requestIds)
      if (validIds.length === 0) throw new Error('No valid request ids.')
      return postDropWorkflowEscalate({
        request_ids: validIds,
        target_role: 'legal',
      })
    },
    onSuccess: async (_data, requestIds) => {
      actionToast.success({
        title: 'Assigned to legal',
        description: `${filterRequestUuids(requestIds).length} updated`,
      })
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error, requestIds) => {
      actionToast.error({
        title: 'Assign to legal failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => bulkEscalateMutation.mutate(requestIds),
        },
      })
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
        if (target.group !== 'legal') {
          throw new Error(
            'Owner matching review is a vertical catalog assignment, not a request assignment.',
          )
        }
        return postDropWorkflowEscalate({
          request_ids: requestIds,
          target_role: 'legal',
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

  const loading = attentionListQuery.isPending && !attentionListQuery.data
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

  function selectedWorkRequestIds(): string[] {
    if (allFilteredSelected) {
      return filterRequestUuids(filteredItems.map((item) => item.request_id))
    }
    return requestIdsFromSelectedReviewItems(filteredItems, selectedIds)
  }

  function selectedWorkTargets() {
    if (allFilteredSelected) {
      return selectedReviewTargets(
        filteredItems,
        new Set(filteredItems.map((item) => inboxReviewItemKey(item))),
      )
    }
    return selectedReviewTargets(filteredItems, selectedIds)
  }

  function runBulk(action: 'fulfill' | 'decline', responseStatus?: DropResponseStatusCode) {
    // Select-all acts on every row loaded so far (server-paginated growing window),
    // not the whole server-side total — see the "(of N)" hint in the selection chip.
    const targets = selectedWorkTargets()
    const requestIds = filterRequestUuids(targets.map((target) => target.request_id))
    if (targets.length === 0) return
    bulkMutation.mutate({ action, requestIds, responseStatus, targets })
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
    <section className="flex h-[calc(100vh-5rem)] flex-col gap-2">
      <ConfirmActionDialog
        open={bulkConfirm === 'fulfill'}
        onOpenChange={(open) => {
          if (!open && !bulkMutation.isPending) setBulkConfirm(null)
          if (open) setBulkFulfillStatus(bulkFulfillSuggestion)
        }}
        title={`${dataOwnerPersona ? 'Confirm' : 'Fulfill'} ${allFilteredSelected ? filteredIds.length : selectedCount} request${
          (allFilteredSelected ? filteredIds.length : selectedCount) === 1 ? '' : 's'
        }?`}
        description={
          dataOwnerPersona
            ? 'Confirm the match result for the selected items.'
            : 'Selected items leave matching review with the CA DROP status result you confirm below.'
        }
        confirmLabel={dataOwnerPersona ? 'Confirm selected' : 'Fulfill selected'}
        confirming={bulkMutation.isPending && bulkConfirm === 'fulfill'}
        confirmDisabled={bulkFulfillStatus == null || !bulkFulfillDwidsReady}
        onConfirm={() => {
          if (bulkFulfillStatus != null) runBulk('fulfill', bulkFulfillStatus)
        }}
      >
        <DropResponseStatusPicker
          value={bulkFulfillStatus}
          onChange={handleBulkFulfillStatusChange}
          disabled={bulkMutation.isPending}
          suggested={bulkFulfillSuggestedStatus}
          contacts={singleNeedsAttentionBulkId ? bulkFulfillContacts : undefined}
          selectedDwids={bulkSelectedDwids}
          onSelectedDwidsChange={setBulkSelectedDwids}
          persona={dataOwnerPersona ? 'data_owner' : legalPersona ? 'legal' : 'ops'}
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
            requestIds: selectedWorkRequestIds(),
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
          const requestIds = selectedWorkRequestIds()
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
          const requestIds = selectedWorkRequestIds()
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
          const requestIds = selectedWorkRequestIds()
          if (requestIds.length > 0) bulkNoticeApproveMutation.mutate(requestIds)
        }}
      />
      <div className="taste-panel flex min-h-0 flex-1 flex-col overflow-hidden">
        {attentionListQuery.isFetching && !attentionListQuery.isPending ? (
          <span className="sr-only">Refreshing</span>
        ) : null}
        {bulkMutation.isPending ||
        bulkAssignMutation.isPending ||
        triageBulkPending ||
        noticeBulkPending ? (
          <span className="sr-only" role="status" aria-live="polite">
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
          <InboxCatalogFilterToolbar
            vertical={verticalFilter}
            verticalOptions={verticalFilterOptions}
            onPatch={patchInboxCatalogSearch}
            hideVertical={dataOwnerPersona}
          />
          <InboxViewSettingsPopover
            groupByBatch={groupByBatch}
            groupBySystem={effectiveGroupBySystem}
            groupByStatus={groupByStatus}
            matchFilter={matchFilter}
            dueFilter={dueFilter}
            systemFilter={showSystem ? systemFilter : undefined}
            sourceFilter={sourceFilter}
            stepFilter={stepFilter}
            systemOptions={systemFilterOptions}
            sourceOptions={sourceOptions}
            stepOptions={stepOptions}
            matchOptions={matchOptions.map(([id, count]) => ({
              id,
              label: matchTypeLabel(id, dataOwnerPersona),
              count,
            }))}
            dueOptions={dueOptions.map(([id, count]) => ({
              id,
              label:
                id === 'overdue' ? 'Overdue' : id === 'due_soon' ? 'Soon' : 'On track',
              count,
            }))}
            showSystem={showSystem}
            onChange={(patch) => {
              if ('groupByBatch' in patch && patch.groupByBatch != null) {
                setGroupByBatchOverride(patch.groupByBatch)
              }
              if ('groupBySystem' in patch && patch.groupBySystem != null) {
                setGroupBySystem(patch.groupBySystem)
              }
              if ('groupByStatus' in patch && patch.groupByStatus != null) {
                setGroupByStatus(patch.groupByStatus)
              }
              if ('matchFilter' in patch && patch.matchFilter) {
                setMatchFilter(patch.matchFilter as MatchFilter)
              }
              if ('dueFilter' in patch && patch.dueFilter) {
                setDueFilter(patch.dueFilter as DueFilter)
              }
              if ('system' in patch) {
                patchInboxCatalogSearch({ system: patch.system })
              }
              if ('source' in patch) {
                patchInboxCatalogSearch({ source: patch.source })
              }
              if ('step' in patch) {
                patchInboxCatalogSearch({
                  step: patch.step as InboxCatalogSearch['step'],
                })
              }
            }}
          />
          {bulkFilter != null ? (
            <span className="ml-auto flex shrink-0 items-center gap-1.5 text-[0.65rem]">
              <span className="text-mute">
                {filteredItems[0]
                  ? inboxDateSourceLabel(filteredItems[0])
                  : 'This batch'}
              </span>
              <button
                type="button"
                className="font-medium text-habeas-navy underline-offset-2 hover:underline"
                onClick={() =>
                  void navigate({
                    to: '/requests/needs-attention',
                    search: (prev) => mergeInboxCatalogSearch(prev, { bulk: undefined }),
                  })
                }
              >
                Clear
              </button>
            </span>
          ) : null}
        </div>

        {showInboxConnectorNotifications ? (
          <div className="shrink-0 border-b border-line px-3 py-2">
            <InboxConnectorNotificationsPanel
              reminders={me?.connector_reminders}
              gate={inboxConnectorGate}
              showOwnerLink={dataOwnerPersona}
              connectorsVerticalId={
                me?.connector_reminders?.find((reminder) => reminder.severity === 'overdue')
                  ?.vertical_id ?? me?.connector_reminders?.[0]?.vertical_id ?? null
              }
            />
          </div>
        ) : null}

        <div
          className={cn(
            'grid min-h-0 flex-1 grid-cols-1 overflow-hidden',
            listChrome.pinnedCollapsed
              ? INBOX_LIST_COLLAPSED_COLS
              : INBOX_LIST_EXPANDED_COLS,
          )}
        >
        <div
          className={cn(
            'relative min-h-0',
            mobilePane === 'detail' ? 'hidden md:block' : 'block',
          )}
        >
        <div
          className={cn(
            'flex h-full min-h-0 flex-col border-line bg-paper md:border-r',
            listChrome.pinnedCollapsed &&
              listChrome.hoverOpen &&
              INBOX_LIST_HOVER_FLYOUT,
          )}
          onMouseEnter={listChrome.onRailEnter}
          onMouseLeave={listChrome.onRailLeave}
        >
          <div
            className={cn(
              'flex shrink-0 items-center border-b border-line',
              listChrome.effectiveCollapsed
                ? 'flex-col gap-1.5 px-1 py-1.5'
                : 'flex-wrap gap-2 px-2 py-1',
            )}
          >
            <button
              type="button"
              className={cn(
                'inline-flex shrink-0 items-center justify-center rounded-md border border-line text-ink-soft hover:bg-panel/60 hover:text-ink',
                listChrome.effectiveCollapsed ? 'h-7 w-7 text-[0.8rem]' : 'h-6 w-6 text-[0.7rem]',
              )}
              aria-pressed={listChrome.pinnedCollapsed}
              aria-label={
                listChrome.pinnedCollapsed ? 'Expand inbox list' : 'Collapse inbox list'
              }
              title={listChrome.pinnedCollapsed ? 'Expand list' : 'Collapse list'}
              onClick={() => listChrome.setPinnedCollapsed(!listChrome.pinnedCollapsed)}
            >
              {listChrome.pinnedCollapsed ? '›' : '‹'}
            </button>
            {listChrome.effectiveCollapsed ? (
              <span className="text-[0.6rem] tabular-nums text-mute">
                {filteredItems.length}
              </span>
            ) : null}
            <div
              className={cn(
                'flex min-w-0 flex-1 flex-wrap items-center gap-2',
                listChrome.effectiveCollapsed && 'hidden',
              )}
            >
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
                    ? `All ${filteredIds.length}`
                    : `${selectedInFilterCount} of ${filteredIds.length}`}
                  <button
                    type="button"
                    className="ml-1.5 text-mute hover:text-ink"
                    onClick={() => setSelectedIds(new Set())}
                    aria-label="Clear selection"
                  >
                    ×
                  </button>
                </span>
              ) : null}
            </div>
            </div>
          </div>

          <div className={cn('flex min-h-0 flex-1 flex-col', listChrome.effectiveCollapsed && 'hidden')}>
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
              {inboxKind === 'matching' ? null : (
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
              )}
            </div>
          ) : null}

          <div className="min-h-0 flex-1 overflow-y-auto">
            {loading ? (
              <div className="p-4">
                <SkeletonLines lines={6} />
              </div>
            ) : null}
            {attentionListQuery.isError ? (
              <p className="p-4 text-xs text-red-700">Could not load inbox.</p>
            ) : null}
            {!loading && !attentionListQuery.isError && filteredItems.length === 0 ? (
              <p className="p-6 text-xs text-ink-soft">
                {legalPersona
                  ? legalFilterEmptyMessage(legalInboxFilter)
                  : items.length === 0
                    ? inboxKind === 'fulfillment'
                      ? 'No kicked-off fulfillment waiting — Legal kickoff comes first.'
                      : 'Nothing needs attention right now.'
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
                              : inboxKind === 'fulfillment'
                                ? 'No kicked-off fulfillment in this filter.'
                                : inboxKind === 'pending_tasks'
                                  ? 'No pending tasks for your assigned verticals.'
                                  : 'No items match the current view.'}
              </p>
            ) : null}

            {!loading && !attentionListQuery.isError && filteredItems.length > 0 ? (
              <ul
                key={`inbox-group-${groupByBatch ? 'b' : ''}${groupBySystem ? 's' : ''}${groupByStatus ? 'r' : ''}-n`}
                className={cn(
                  groupingActive ? 'space-y-0 bg-canvas/40 p-0' : 'divide-y divide-line',
                )}
              >
                <InboxQueueRows
                  groupingActive={groupingActive}
                  rows={pagedInboxRows}
                  selectedKeys={selectedIds}
                  activeTarget={activeTarget}
                  expandedThreads={expandedThreads}
                  dataOwnerPersona={dataOwnerPersona}
                  legalPersona={legalPersona}
                  connectorReminders={me?.connector_reminders}
                  connectorGate={inboxConnectorGate}
                  onToggleThreadSelect={toggleThreadSelect}
                  onToggleThreadExpand={toggleThreadExpand}
                  onOpenThread={(batchKey) => {
                    toggleThreadExpand(batchKey)
                    setActiveTarget({ kind: 'thread', batchKey })
                    setMobilePane('detail')
                  }}
                  onToggleItem={toggleId}
                  onOpenItem={(itemKey) => {
                    setActiveTarget({ kind: 'request', itemKey })
                    setMobilePane('detail')
                  }}
                />
              </ul>
            ) : null}
          </div>

          {!loading && !attentionListQuery.isError && filteredItems.length > 0 ? (
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
        </div>
        </div>

        <div
          className={cn(
            'flex min-h-0 min-w-0 flex-col overflow-hidden',
            mobilePane === 'queue' ? 'hidden md:flex' : 'flex',
          )}
        >
          {activeThread ? (
            <ThreadReviewPane
              batchLabel={activeThread.batchLabel}
              items={activeThread.items}
              stackKind={activeThread.stackKind}
              canReviewActions={canReviewActions}
              dataOwnerPersona={dataOwnerPersona}
              assigneeCandidates={assigneeCandidates}
              onBulkAssign={(target) => {
                bulkAssignMutation.mutate({
                  requestIds: filterRequestUuids(
                    activeThread.items.map((item) => item.request_id),
                  ),
                  target,
                })
              }}
              actionPending={
                bulkMutation.isPending ||
                bulkEscalateMutation.isPending ||
                bulkAssignMutation.isPending
              }
              onBackToQueue={() => setMobilePane('queue')}
              onOpenDetail={(item, trigger) => {
                detailOverlay.openOverlay(
                  item.request_id,
                  trigger,
                  inboxItemToSeedRequest(item),
                  item.vertical,
                  inboxItemSystemId(item),
                )
              }}
              onPromoteAll={(responseStatus) => {
                const targets = selectedReviewTargets(
                  activeThread.items,
                  new Set(activeThread.items.map((item) => inboxReviewItemKey(item))),
                )
                bulkMutation.mutate({
                  action: 'fulfill',
                  requestIds: filterRequestUuids(targets.map((target) => target.request_id)),
                  responseStatus,
                  targets,
                })
              }}
              onDeclineAll={() => {
                const targets = selectedReviewTargets(
                  activeThread.items,
                  new Set(activeThread.items.map((item) => inboxReviewItemKey(item))),
                )
                bulkMutation.mutate({
                  action: 'decline',
                  requestIds: filterRequestUuids(targets.map((target) => target.request_id)),
                  targets,
                })
              }}
              onEscalateAll={() => {
                bulkEscalateMutation.mutate(
                  activeThread.items.map((item) => item.request_id),
                )
              }}
              onSeeMoreDetails={() => {
                const first = activeThread.items[0]
                if (first) {
                  setActiveTarget({
                    kind: 'request',
                    itemKey: inboxReviewItemKey(first),
                  })
                }
                setMobilePane('detail')
              }}
            />
          ) : activeItem ? (
            <InboxReviewPane
              item={activeItem}
              canReviewActions={canReviewActions}
              assigneeCandidates={assigneeCandidates}
              legalPersona={legalPersona}
              dataOwnerPersona={dataOwnerPersona}
              inboxKind={inboxKind}
              onBackToQueue={() => setMobilePane('queue')}
              onOpenDetail={(item, trigger) => {
                detailOverlay.openOverlay(
                  item.request_id,
                  trigger,
                  inboxItemToSeedRequest(item),
                  item.vertical,
                  inboxItemSystemId(item),
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
        vertical={detailOverlay.vertical}
        system={detailOverlay.system}
      />
    </section>
  )
}
