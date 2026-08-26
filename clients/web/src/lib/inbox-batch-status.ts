/**
 * Inbox grouping — Batch stacks (date+source keys, default), optional system /
 * status stacks, and matching-disposition / DROP labels for
 * `/requests/needs-attention`.
 *
 * Match type and identifier type (`match_type`, `matched_via`, list type) are
 * filters, not row identity. Batch and system stacks must not split phone vs
 * email into separate groups. Group-by System uses catalog data-system labels,
 * never intake source. Group-by Status is matching disposition, wizard block
 * (needs connection / refresh), or confirmed DROP — not identifier surfaces.
 */

import type {
  ConnectorReminder,
  DropResponseStatusCode,
  NeedsAttentionItem,
} from '@/lib/api'
import { suggestedDropResponseStatus } from '@/lib/api'
import {
  matchingConnectorGateBannerCopy,
  matchingConnectorGateChip,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import { buildReminderBannerItems } from '@/lib/owner-connector-ui'
import {
  catalogSystemDisplayLabel,
  isWorkbenchStageKey,
  opsStageToWorkbench,
  TEST_VERTICAL_ID,
  type WorkbenchStageKey,
} from '@/lib/legalJourneyLabels'
import { coalesceInboxReviewItems } from '@/lib/inbox-status-lab'
import { filterRequestUuids } from '@/lib/utils'

/** Status bucket — matching disposition, wizard block, or confirmed DROP 3/4/5. */
export type InboxBatchStatusKey =
  | 'needs_connection'
  | 'needs_refresh'
  | 'single_match'
  | 'multi_match'
  | 'not_found'
  | 'unknown'
  | 'drop_3'
  | 'drop_4'
  | 'drop_5'
  | 'triage'
  | 'notice'
  | 'delivery'
  | 'communications'
  | 'assignment_to_legal'
  | 'fulfillment'
  | 'other'

export const INBOX_BATCH_STATUS_ORDER: InboxBatchStatusKey[] = [
  'needs_connection',
  'needs_refresh',
  'single_match',
  'drop_3',
  'multi_match',
  'drop_4',
  'not_found',
  'drop_5',
  'unknown',
  'fulfillment',
  'triage',
  'assignment_to_legal',
  'notice',
  'delivery',
  'communications',
  'other',
]

export type InboxStatusKeyOptions = {
  reminders?: ConnectorReminder[] | null
  gate?: MatchingConnectorGate | null
}

const DROP_STATUS_LABELS: Record<number, string> = {
  3: 'Deleted',
  4: 'Opted out',
  5: 'Not found',
}

const OWNER_DROP_STATUS_LABELS: Record<number, string> = {
  3: 'Confirm match',
  4: 'Multi-person',
  5: 'Not a match',
}

const INTAKE_SOURCE_LABELS: Record<string, string> = {
  drop: 'CA DROP',
  webform: 'Gravity Forms',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

const UNDATED_KEY = 'undated'
const UNASSIGNED_SYSTEM_KEY = 'unassigned'

export type InboxBatchParts = { key: string; label: string }

function inboxItemLocalDate(
  item: Pick<NeedsAttentionItem, 'requested_at' | 'received_at'>,
): Date | null {
  const raw = item.requested_at?.trim() || item.received_at?.trim() || ''
  if (!raw) return null
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return null
  return date
}

/** Local calendar day `YYYY-MM-DD` — date only, stable on a given machine. */
function inboxLocalDateKey(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function inboxLocalDateLabel(date: Date): string {
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function inboxIntakeSourceLabel(source: string | null | undefined): string {
  const trimmed = (source ?? '').trim()
  if (!trimmed) return 'Unknown'
  return INTAKE_SOURCE_LABELS[trimmed] ?? trimmed
}

/**
 * Catalog system id — `system`, then `system_id`. Never a composite POST key.
 * Not match type / identifier type.
 */
export function inboxItemSystemId(
  item: Pick<NeedsAttentionItem, 'system' | 'system_id'>,
): string | null {
  return item.system?.trim() || item.system_id?.trim() || null
}

function inboxSystemStackKey(
  item: Pick<NeedsAttentionItem, 'system' | 'system_id'>,
): string {
  return inboxItemSystemId(item) ?? UNASSIGNED_SYSTEM_KEY
}

function inboxSystemStackLabel(
  item: Pick<NeedsAttentionItem, 'system' | 'system_id' | 'system_label' | 'vertical'>,
): string {
  return (
    catalogSystemDisplayLabel(inboxItemSystemId(item), {
      vertical: item.vertical,
      systemLabel: item.system_label,
    }) || 'Unassigned system'
  )
}

/** Date + intake source key — not process id, match type, or identifier type. */
export function inboxDateSourceKey(
  item: Pick<NeedsAttentionItem, 'requested_at' | 'received_at' | 'intake_source'>,
): string {
  const date = inboxItemLocalDate(item)
  const dateKey = date ? inboxLocalDateKey(date) : UNDATED_KEY
  const source = (item.intake_source ?? '').trim() || 'unknown'
  return `${dateKey}::${source}`
}

/** Visible Batch stack title — e.g. `Aug 21 · CA DROP`. Never `#42`. */
export function inboxDateSourceLabel(
  item: Pick<NeedsAttentionItem, 'requested_at' | 'received_at' | 'intake_source'>,
): string {
  const date = inboxItemLocalDate(item)
  const dateLabel = date ? inboxLocalDateLabel(date) : 'Undated'
  return `${dateLabel} · ${inboxIntakeSourceLabel(item.intake_source)}`
}

/** User-facing Batch stack title — same value as `inboxDateSourceLabel`. */
export function inboxBatchLabel(
  item: Pick<NeedsAttentionItem, 'requested_at' | 'received_at' | 'intake_source'>,
): string {
  return inboxDateSourceLabel(item)
}

/** Lite snapshot / process-list fields for a collapsed pipeline row. */
export type BulkProcessLiteRow = {
  process_at?: string | null
  intake_source?: string | null
  label?: string | null
  download_status?: string | null
  request_rows?: number
  raw_rows?: number
  overall?: {
    percent?: number
    current_stage?: string
    status?: string
  } | null
}

function bulkProcessLocalDate(processAt: string | null | undefined): Date | null {
  const raw = processAt?.trim() || ''
  if (!raw) return null
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return null
  return date
}

/** inboxLocalDateLabel style plus year — `Aug 21, 2026`. */
function bulkProcessLocalDateLabel(date: Date): string {
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

/** drop → CA DROP via inboxIntakeSourceLabel. Empty → Unknown. */
export function bulkProcessSourceLabel(intakeSource: string | null | undefined): string {
  return inboxIntakeSourceLabel(intakeSource)
}

/**
 * Human collapsed title. Prefer date · source (e.g. Aug 21, 2026 · CA DROP).
 * Fall back to `label`, then source, then date, then '—' only if nothing exists.
 * Never return empty string.
 */
export function bulkProcessCollapsedTitle(row: BulkProcessLiteRow): string {
  const date = bulkProcessLocalDate(row.process_at)
  const dateLabel = date ? bulkProcessLocalDateLabel(date) : ''
  const sourceRaw = (row.intake_source ?? '').trim()
  const sourceLabel = sourceRaw ? inboxIntakeSourceLabel(sourceRaw) : ''
  const label = row.label?.trim() ?? ''

  if (dateLabel && sourceLabel) return `${dateLabel} · ${sourceLabel}`
  if (label) return label
  if (sourceLabel) return sourceLabel
  if (dateLabel) return dateLabel
  return '—'
}

/** e.g. "1840000 req" when request_rows is a number; null if unknown. */
export function bulkProcessCollapsedCounts(row: BulkProcessLiteRow): string | null {
  if (typeof row.request_rows !== 'number') return null
  return `${row.request_rows} req`
}

/** overall.status or download_status, underscores → spaces. '—' only if both missing. */
export function bulkProcessCollapsedStatus(row: BulkProcessLiteRow): string {
  const raw =
    (row.overall?.status ?? '').trim() || (row.download_status ?? '').trim()
  if (!raw) return '—'
  return raw.replaceAll('_', ' ')
}

/** overall.percent if a number, else null */
export function bulkProcessCollapsedPercent(row: BulkProcessLiteRow): number | null {
  const percent = row.overall?.percent
  return typeof percent === 'number' ? percent : null
}

/** Default stack identity for inbox grouping builders. */
export function inboxDateSourceParts(
  item: Pick<NeedsAttentionItem, 'requested_at' | 'received_at' | 'intake_source'>,
): InboxBatchParts {
  return { key: inboxDateSourceKey(item), label: inboxDateSourceLabel(item) }
}

export type InboxGroupingStack = {
  key: string
  label: string
  items: NeedsAttentionItem[]
}

export type InboxGroupingOptions = {
  byDateSource?: boolean
  bySystem?: boolean
  byStatus?: boolean
  reminders?: ConnectorReminder[] | null
  gate?: MatchingConnectorGate | null
}

function collectInboxGroupingStacks(
  items: NeedsAttentionItem[],
  partFor: (item: NeedsAttentionItem) => InboxBatchParts,
): InboxGroupingStack[] {
  const groups = new Map<string, InboxGroupingStack>()
  for (const item of items) {
    const parts = partFor(item)
    const existing = groups.get(parts.key)
    if (existing) {
      existing.items.push(item)
    } else {
      groups.set(parts.key, { key: parts.key, label: parts.label, items: [item] })
    }
  }
  return [...groups.values()].sort((left, right) => {
    const leftTime = left.items[0]?.requested_at ?? left.items[0]?.received_at ?? ''
    const rightTime = right.items[0]?.requested_at ?? right.items[0]?.received_at ?? ''
    const byTime = leftTime.localeCompare(rightTime)
    if (byTime !== 0) return byTime
    return left.label.localeCompare(right.label)
  })
}

/** One Batch stack per local calendar day + intake source. Does not split phone vs email. */
export function groupInboxItemsByDateSource(
  items: NeedsAttentionItem[],
): InboxGroupingStack[] {
  return collectInboxGroupingStacks(items, inboxDateSourceParts)
}

/**
 * One stack per catalog data system (`system` then `system_id`).
 * Label is `system_label` / system id — never intake source.
 */
export function groupInboxItemsBySystem(
  items: NeedsAttentionItem[],
): InboxGroupingStack[] {
  return collectInboxGroupingStacks(items, (item) => ({
    key: inboxSystemStackKey(item),
    label: inboxSystemStackLabel(item),
  }))
}

/** Four-stage workbench step from `current_stage` — ingest | matching | fulfillment | notice. */
export function inboxItemStepKey(
  item: Pick<NeedsAttentionItem, 'current_stage'>,
): WorkbenchStageKey {
  const stage = (item.current_stage ?? '').trim().toLowerCase()
  if (isWorkbenchStageKey(stage)) return stage
  return opsStageToWorkbench(stage) ?? 'ingest'
}

function inboxGroupingDimensionParts(
  item: NeedsAttentionItem,
  options: {
    dateSource: boolean
    system: boolean
    status: boolean
    statusContext?: InboxStatusKeyOptions
  },
  ownerLanguage: boolean,
): InboxBatchParts {
  const parts: InboxBatchParts[] = []
  if (options.dateSource) parts.push(inboxDateSourceParts(item))
  if (options.system) {
    parts.push({ key: inboxSystemStackKey(item), label: inboxSystemStackLabel(item) })
  }
  if (options.status) {
    const statusKey = inboxWorkStatusKey(item, options.statusContext)
    parts.push({
      key: statusKey,
      label: inboxBatchStatusLabel(statusKey, ownerLanguage),
    })
  }
  if (parts.length === 0) return inboxDateSourceParts(item)
  return {
    key: parts.map((part) => part.key).join('::'),
    label: parts.map((part) => part.label).join(' · '),
  }
}

/**
 * Stacks the inbox page can render.
 * Default is Batch (date+source keys). System and status are optional.
 * Multi-select is SQL GROUP BY: one stack per unique combination of selected
 * dimensions. Match type is a filter, not a grouping dimension.
 */
export function buildInboxGroupingStacks(
  items: NeedsAttentionItem[],
  options: InboxGroupingOptions = {},
  ownerLanguage = false,
): InboxGroupingStack[] {
  const bySystem = options.bySystem === true
  const byStatus = options.byStatus === true
  const byDateSource = options.byDateSource === true || (!bySystem && !byStatus)
  const statusContext: InboxStatusKeyOptions = {
    reminders: options.reminders,
    gate: options.gate,
  }
  if (byStatus && !byDateSource && !bySystem) {
    return groupInboxItemsByBatchStatus(items, ownerLanguage, statusContext)
  }
  return collectInboxGroupingStacks(items, (item) =>
    inboxGroupingDimensionParts(
      item,
      {
        dateSource: byDateSource,
        system: bySystem,
        status: byStatus,
        statusContext,
      },
      ownerLanguage,
    ),
  )
}

function workTypeFallbackKey(item: NeedsAttentionItem): InboxBatchStatusKey {
  const kind = (item.kind ?? '').trim().toLowerCase()
  const reason = (item.reason ?? '').trim().toLowerCase()
  const stage = (item.current_stage ?? '').trim().toLowerCase()

  if (kind === 'notice' || reason === 'notice.review' || stage === 'notice') return 'notice'
  if (
    kind === 'delivery' ||
    reason === 'access.delivery' ||
    reason === 'delivery.confirm' ||
    stage === 'delivery'
  ) {
    return 'delivery'
  }
  if (
    kind === 'triage' ||
    item.assignment?.kind === 'triage' ||
    stage === 'triage'
  ) {
    return 'triage'
  }
  if (
    kind === 'escalations' ||
    item.assignment?.kind === 'escalate' ||
    item.assignment?.target_role === 'legal'
  ) {
    return 'assignment_to_legal'
  }
  if (
    reason.startsWith('comms.') ||
    reason.includes('communication') ||
    stage === 'comms'
  ) {
    return 'communications'
  }
  if (
    stage === 'fulfillment' ||
    stage === 'fulfill' ||
    reason === 'fulfillment.kickoff' ||
    reason === 'fulfillment.owner'
  ) {
    return 'fulfillment'
  }
  return 'other'
}

/** Derive the matching-attempt or confirmed DROP bucket (no wizard block). */
export function inboxBatchStatusKey(item: NeedsAttentionItem): InboxBatchStatusKey {
  if (item.intake_source === 'drop' && item.response_status != null) {
    if (item.response_status === 3) return 'drop_3'
    if (item.response_status === 4) return 'drop_4'
    if (item.response_status === 5) return 'drop_5'
  }

  const matchType = (item.match_type ?? '').trim()
  if (matchType === 'single_match') return 'single_match'
  if (matchType === 'multi_match') return 'multi_match'
  if (matchType === 'not_found') return 'not_found'
  if (matchType) return 'unknown'

  if (
    item.reason === 'matching.review' ||
    item.kind === 'matching' ||
    item.current_stage === 'review' ||
    item.match_type != null
  ) {
    return 'unknown'
  }

  return workTypeFallbackKey(item)
}

/** Same labels as inbox Status stacks / DROP status pills. */
export function inboxBatchStatusLabel(
  key: InboxBatchStatusKey,
  ownerLanguage = false,
): string {
  switch (key) {
    case 'needs_connection':
      return 'Needs connection'
    case 'needs_refresh':
      return 'Needs refresh'
    case 'single_match':
      return ownerLanguage ? 'Confirm match' : 'Single match'
    case 'multi_match':
      return 'Multi-person'
    case 'not_found':
      return ownerLanguage ? 'Not a match' : 'Not found'
    case 'drop_3':
      return ownerLanguage
        ? OWNER_DROP_STATUS_LABELS[3]
        : `${DROP_STATUS_LABELS[3]} (3)`
    case 'drop_4':
      return ownerLanguage
        ? OWNER_DROP_STATUS_LABELS[4]
        : `${DROP_STATUS_LABELS[4]} (4)`
    case 'drop_5':
      return ownerLanguage
        ? OWNER_DROP_STATUS_LABELS[5]
        : `${DROP_STATUS_LABELS[5]} (5)`
    case 'unknown':
      return 'No match data'
    case 'triage':
      return 'Pre-matching hold'
    case 'notice':
      return 'Notice'
    case 'delivery':
      return 'Delivery'
    case 'communications':
      return 'Comms'
    case 'assignment_to_legal':
      return 'Assignment to legal'
    case 'fulfillment':
      return 'Fulfillment'
    default:
      return 'Other'
  }
}

/** Short stack subtitle — e.g. Exact 1:1 for homogeneous single-match batches. */
export function inboxBatchStatusStackSubtitle(
  items: NeedsAttentionItem[],
  ownerLanguage = false,
): string | null {
  if (items.length === 0) return null
  const keys = new Set(items.map((item) => inboxBatchStatusKey(item)))
  if (keys.size !== 1) return null
  const key = keys.values().next().value!
  if (key === 'single_match' || key === 'drop_3') {
    return ownerLanguage ? 'Confirm match' : 'Exact 1:1'
  }
  return inboxBatchStatusLabel(key, ownerLanguage)
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

/** Kicked-off fulfillment on the data-owner Inbox · Fulfillment lane (R61). */
export function isOwnerFulfillmentItem(item: NeedsAttentionItem): boolean {
  const kind = item.kind
  if (
    kind === 'triage' ||
    item.assignment?.kind === 'triage' ||
    item.current_stage === 'triage'
  ) {
    return false
  }
  if (
    kind === 'notice' ||
    item.reason === 'notice.review' ||
    item.current_stage === 'notice'
  ) {
    return false
  }
  if (
    kind === 'delivery' ||
    item.reason === 'access.delivery' ||
    item.reason === 'delivery.confirm' ||
    item.current_stage === 'delivery'
  ) {
    return false
  }
  const isEscalation = kind === 'escalations' || item.assignment?.kind === 'escalate'
  if (
    isEscalation &&
    (item.assignment?.target_role === 'legal' || kind === 'escalations')
  ) {
    return false
  }
  const stage = (item.current_stage ?? '').trim().toLowerCase()
  const reason = (item.reason ?? '').trim().toLowerCase()
  return (
    stage === 'fulfillment' ||
    stage === 'fulfill' ||
    reason === 'fulfillment.kickoff' ||
    reason === 'fulfillment.owner'
  )
}

export type InboxBatchStatusSection = {
  key: InboxBatchStatusKey
  label: string
  items: NeedsAttentionItem[]
}

/** Group inbox items by work status (stable sort order). */
export function groupInboxItemsByBatchStatus(
  items: NeedsAttentionItem[],
  ownerLanguage = false,
  statusContext?: InboxStatusKeyOptions,
): InboxBatchStatusSection[] {
  const buckets = new Map<InboxBatchStatusKey, NeedsAttentionItem[]>()
  for (const item of items) {
    const key = inboxWorkStatusKey(item, statusContext)
    const list = buckets.get(key) ?? []
    list.push(item)
    buckets.set(key, list)
  }
  return INBOX_BATCH_STATUS_ORDER.filter((key) => (buckets.get(key)?.length ?? 0) > 0).map(
    (key) => ({
      key,
      label: inboxBatchStatusLabel(key, ownerLanguage),
      items: buckets.get(key) ?? [],
    }),
  )
}

export type InboxConnectorNotifGroup = {
  key: string
  label: string
  chipLabel: string
  chipVariant: 'ok' | 'fail' | 'run' | 'wait' | 'default'
  reminders: ConnectorReminder[]
  gate?: MatchingConnectorGate
  title: string
  description: string
}

const INBOX_CONNECTOR_REMINDER_CODES = new Set([
  'upload_stale',
  'rotation_overdue',
  'wizard_incomplete',
  'upload_approaching',
  'rotation_approaching',
])

/**
 * Group connector reminders + matching gate banner payloads by reminder code / gate status.
 * Approaching-only reminders stay in their code bucket; overdue sorts first within inbox.
 */
export function groupInboxConnectorNotifications(options: {
  reminders?: ConnectorReminder[] | null
  gate?: MatchingConnectorGate | null
}): InboxConnectorNotifGroup[] {
  const reminders = (options.reminders ?? []).filter((reminder) =>
    INBOX_CONNECTOR_REMINDER_CODES.has(reminder.code),
  )
  const groups = new Map<string, InboxConnectorNotifGroup>()

  for (const reminder of reminders) {
    const bannerItems = buildReminderBannerItems([reminder])
    const copy = bannerItems[0]
    const chip =
      reminder.severity === 'overdue'
        ? { label: 'Overdue', variant: 'fail' as const }
        : { label: 'Approaching', variant: 'wait' as const }
    const key = `reminder:${reminder.code}`
    const existing = groups.get(key)
    if (existing) {
      existing.reminders.push(reminder)
    } else {
      groups.set(key, {
        key,
        label: copy?.title ?? reminder.code.replaceAll('_', ' '),
        chipLabel: chip.label,
        chipVariant: chip.variant,
        reminders: [reminder],
        title: copy?.title ?? reminder.code.replaceAll('_', ' '),
        description: copy?.description ?? '',
      })
    }
  }

  const gate = options.gate
  if (gate?.blocked) {
    const chip = matchingConnectorGateChip(gate)
    const reminderForGate = reminders.find(
      (reminder) =>
        reminder.code === gate.gateCode ||
        reminder.system === gate.system,
    )
    const groupKey = reminderForGate
      ? `reminder:${reminderForGate.code}`
      : `gate:${gate.gateCode ?? gate.displayStatus}`
    const existing = groups.get(groupKey)
    const gateCopy = matchingConnectorGateBannerCopy(gate)
    if (existing) {
      existing.gate = gate
      if (reminderForGate && !existing.reminders.includes(reminderForGate)) {
        existing.reminders.push(reminderForGate)
      }
      existing.title = gateCopy.title
      existing.description = gateCopy.description
      existing.chipLabel = chip.label
      existing.chipVariant = chip.variant
    } else {
      groups.set(groupKey, {
        key: groupKey,
        label: chip.label,
        chipLabel: chip.label,
        chipVariant: chip.variant,
        reminders: reminderForGate ? [reminderForGate] : [],
        gate,
        title: gateCopy.title,
        description: gateCopy.description,
      })
    }
  }

  const severityRank = (group: InboxConnectorNotifGroup) => {
    const overdue =
      group.reminders.some((reminder) => reminder.severity === 'overdue') ||
      group.gate?.blocked
    return overdue ? 0 : 1
  }

  return [...groups.values()].sort((left, right) => {
    const bySeverity = severityRank(left) - severityRank(right)
    if (bySeverity !== 0) return bySeverity
    return left.label.localeCompare(right.label)
  })
}

/** Pipeline step — matching result review vs fulfillment kickoff. */
export type InboxBatchStep = 'matching' | 'fulfillment'

export const UNKEYED_INBOX_BATCH_ID = 'u:none'

export type InboxBatchStatusCrossGroup = {
  batchKey: string
  batchLabel: string
  statusKey: InboxBatchStatusKey
  statusLabel: string
  compositeKey: string
  items: NeedsAttentionItem[]
}

export type InboxBatchStatusStepCrossGroup = InboxBatchStatusCrossGroup & {
  step: InboxBatchStep
  stepLabel: string
}

/** One stack per (date+source, result status) — e.g. Aug 21 · CA DROP · Single match. */
export function buildInboxBatchStatusCrossGroups(
  items: NeedsAttentionItem[],
  batchParts: (item: NeedsAttentionItem) => InboxBatchParts,
  ownerLanguage = false,
): InboxBatchStatusCrossGroup[] {
  const groups = new Map<string, InboxBatchStatusCrossGroup>()

  for (const item of items) {
    const batch = batchParts(item)
    const statusKey = inboxBatchStatusKey(item)
    const compositeKey = `${batch.key}::${statusKey}`
    const existing = groups.get(compositeKey)
    if (existing) {
      existing.items.push(item)
    } else {
      groups.set(compositeKey, {
        batchKey: batch.key,
        batchLabel: batch.label,
        statusKey,
        statusLabel: inboxBatchStatusLabel(statusKey, ownerLanguage),
        compositeKey,
        items: [item],
      })
    }
  }

  const statusRank = new Map(
    INBOX_BATCH_STATUS_ORDER.map((key, index) => [key, index] as const),
  )

  return [...groups.values()].sort((left, right) => {
    const leftTime = left.items[0]?.requested_at ?? ''
    const rightTime = right.items[0]?.requested_at ?? ''
    const byTime = leftTime.localeCompare(rightTime)
    if (byTime !== 0) return byTime
    const byStatus =
      (statusRank.get(left.statusKey) ?? 99) - (statusRank.get(right.statusKey) ?? 99)
    if (byStatus !== 0) return byStatus
    return left.batchLabel.localeCompare(right.batchLabel)
  })
}

/** Prefer download attempt id; fall back to ZIP member name (seed/broker rows). */
export function inboxBatchId(item: NeedsAttentionItem): string {
  if (item.bulk_process_id != null) return `p:${item.bulk_process_id}`
  if (item.source_csv_filename) return `c:${item.source_csv_filename}`
  return UNKEYED_INBOX_BATCH_ID
}

/**
 * Matching vs fulfillment lane — mirrors `/requests/needs-attention` kind filters
 * (`isMatchingItem` / `isOwnerFulfillmentItem`). Fulfillment stage wins when both apply.
 */
export function inboxBatchStep(item: NeedsAttentionItem): InboxBatchStep {
  const stage = (item.current_stage ?? '').trim().toLowerCase()
  const reason = (item.reason ?? '').trim().toLowerCase()
  if (
    stage === 'fulfillment' ||
    stage === 'fulfill' ||
    reason === 'fulfillment.kickoff' ||
    reason === 'fulfillment.owner'
  ) {
    return 'fulfillment'
  }
  return 'matching'
}

export function inboxBatchStepLabel(step: InboxBatchStep): string {
  return step === 'fulfillment' ? 'Fulfillment' : 'Matching result'
}

export type InboxBatchStatusStepKey = {
  batchId: string
  matchStatus: InboxBatchStatusKey
  step: InboxBatchStep
}

export type InboxBatchStatusStepGroup = {
  key: InboxBatchStatusStepKey
  compositeKey: string
  batchId: string
  matchStatus: InboxBatchStatusKey
  matchStatusLabel: string
  step: InboxBatchStep
  items: NeedsAttentionItem[]
}

function inboxBatchStatusStepCompositeKey(key: InboxBatchStatusStepKey): string {
  return `${key.batchId}::${key.matchStatus}::${key.step}`
}

/** One stack per (batch, match status, pipeline step). */
export function groupInboxByBatchStatusStep(
  items: NeedsAttentionItem[],
  ownerLanguage = false,
): InboxBatchStatusStepGroup[] {
  const groups = new Map<string, InboxBatchStatusStepGroup>()

  for (const item of items) {
    const batchId = inboxBatchId(item)
    const matchStatus = inboxBatchStatusKey(item)
    const step = inboxBatchStep(item)
    const key: InboxBatchStatusStepKey = { batchId, matchStatus, step }
    const compositeKey = inboxBatchStatusStepCompositeKey(key)
    const existing = groups.get(compositeKey)
    if (existing) {
      existing.items.push(item)
    } else {
      groups.set(compositeKey, {
        key,
        compositeKey,
        batchId,
        matchStatus,
        matchStatusLabel: inboxBatchStatusLabel(matchStatus, ownerLanguage),
        step,
        items: [item],
      })
    }
  }

  const statusRank = new Map(
    INBOX_BATCH_STATUS_ORDER.map((statusKey, index) => [statusKey, index] as const),
  )
  const stepRank: Record<InboxBatchStep, number> = { matching: 0, fulfillment: 1 }

  return [...groups.values()].sort((left, right) => {
    const leftTime = left.items[0]?.requested_at ?? ''
    const rightTime = right.items[0]?.requested_at ?? ''
    const byTime = leftTime.localeCompare(rightTime)
    if (byTime !== 0) return byTime
    const byStatus =
      (statusRank.get(left.matchStatus) ?? 99) - (statusRank.get(right.matchStatus) ?? 99)
    if (byStatus !== 0) return byStatus
    const byStep = stepRank[left.step] - stepRank[right.step]
    if (byStep !== 0) return byStep
    return left.batchId.localeCompare(right.batchId)
  })
}

const STEP_ORDER: InboxBatchStep[] = ['matching', 'fulfillment']

/** One stack per (batch, match-result status, lane step) — status lab bulk grouping. */
export function buildInboxBatchStatusStepCrossGroups(
  items: NeedsAttentionItem[],
  batchParts: (item: NeedsAttentionItem) => InboxBatchParts,
  ownerLanguage = false,
): InboxBatchStatusStepCrossGroup[] {
  const groups = new Map<string, InboxBatchStatusStepCrossGroup>()

  for (const item of items) {
    const batch = batchParts(item)
    const statusKey = inboxBatchStatusKey(item)
    const step = inboxBatchStep(item)
    const compositeKey = `${batch.key}::${statusKey}::${step}`
    const existing = groups.get(compositeKey)
    if (existing) {
      existing.items.push(item)
    } else {
      groups.set(compositeKey, {
        batchKey: batch.key,
        batchLabel: batch.label,
        statusKey,
        statusLabel: inboxBatchStatusLabel(statusKey, ownerLanguage),
        step,
        stepLabel: inboxBatchStepLabel(step),
        compositeKey,
        items: [item],
      })
    }
  }

  const statusRank = new Map(
    INBOX_BATCH_STATUS_ORDER.map((key, index) => [key, index] as const),
  )
  const stepRank = new Map(STEP_ORDER.map((key, index) => [key, index] as const))

  return [...groups.values()].sort((left, right) => {
    const leftTime = left.items[0]?.requested_at ?? ''
    const rightTime = right.items[0]?.requested_at ?? ''
    const byTime = leftTime.localeCompare(rightTime)
    if (byTime !== 0) return byTime
    const byStatus =
      (statusRank.get(left.statusKey) ?? 99) - (statusRank.get(right.statusKey) ?? 99)
    if (byStatus !== 0) return byStatus
    const byStep = (stepRank.get(left.step) ?? 99) - (stepRank.get(right.step) ?? 99)
    if (byStep !== 0) return byStep
    return left.batchLabel.localeCompare(right.batchLabel)
  })
}

/**
 * All valid request UUIDs in a stack — Confirm / Decline / Assign-to-legal / status
 * apply must use this list, never `compositeKey` (`p:42::single_match::matching`).
 */
export function stackRequestIds(
  members: Array<Pick<NeedsAttentionItem, 'request_id'>>,
): string[] {
  return filterRequestUuids(members.map((member) => member.request_id))
}

/** Internal batch key for nav/inbox work units — never a visible CSV filename. */
export function inboxPendingWorkBatchKey(
  item: Pick<
    NeedsAttentionItem,
    | 'bulk_process_id'
    | 'source_csv_filename'
    | 'requested_at'
    | 'received_at'
    | 'intake_source'
  >,
): string | null {
  if (item.bulk_process_id != null) return `p:${item.bulk_process_id}`
  const date = inboxItemLocalDate(item)
  const source = (item.intake_source ?? '').trim()
  if (date && source) return inboxDateSourceKey(item)
  const filename = item.source_csv_filename?.trim()
  if (filename) return `c:${filename}`
  return null
}

/**
 * Standalone matching-result identity when the item has no batch.
 * Test vertical fans out by system; other verticals group by request + vertical.
 */
export function inboxStandaloneResultKey(
  item: Pick<NeedsAttentionItem, 'request_id' | 'vertical' | 'system' | 'system_id'>,
): string {
  const vertical = (item.vertical ?? '').trim()
  const system = inboxItemSystemId(item) ?? ''
  if (vertical === TEST_VERTICAL_ID && system) {
    return `${item.request_id}::${system}`
  }
  if (vertical) return `${item.request_id}::${vertical}`
  if (system) return `${item.request_id}::${system}`
  return item.request_id
}

/**
 * Status for a pending work unit / Group-by Status stack.
 * Wizard block wins, then confirmed DROP disposition, then matching attempt.
 * Not identifier surfaces (email/phone/ndz) and not catalog system.
 */
export function inboxWorkStatusKey(
  item: NeedsAttentionItem,
  options?: InboxStatusKeyOptions,
): InboxBatchStatusKey {
  const block = inboxItemConnectorBlock(item, options)
  if (block) return block.kind
  return inboxBatchStatusKey(item)
}

/**
 * Badge work units: unique `(batch_key, status_key)` among pending items.
 * `batch_key` is process id or dated date+source (same as today).
 * `status_key` is matching disposition, needs connection / refresh, or confirmed.
 * Identifier surfaces and people are not dimensions. A batch is not collapsed to 1.
 */
export function inboxPendingWorkUnitCount(
  items: NeedsAttentionItem[],
  options?: InboxStatusKeyOptions,
): number {
  const coalesced = coalesceInboxReviewItems(items)
  const units = new Set<string>()
  for (const item of coalesced) {
    const batchKey = inboxPendingWorkBatchKey(item) ?? `s:${inboxStandaloneResultKey(item)}`
    const statusKey = inboxWorkStatusKey(item, options)
    units.add(`${batchKey}::${statusKey}`)
  }
  return units.size
}

export type InboxConnectorBlockKind = 'needs_connection' | 'needs_refresh'

export type InboxConnectorBlock = {
  kind: InboxConnectorBlockKind
  label: string
}

const REFRESH_REMINDER_CODES = new Set([
  'upload_stale',
  'upload_approaching',
  'rotation_overdue',
  'rotation_approaching',
])

const CONNECTION_REMINDER_CODES = new Set(['wizard_incomplete'])

export type InboxConnectorBlockDetail = {
  result_kind?: string | null
  matched_contacts_status?: string | null
  system?: string | null
}

function itemHasConnectableSystem(
  item: Pick<NeedsAttentionItem, 'system' | 'system_id' | 'system_label' | 'vertical'>,
): boolean {
  return Boolean(
    catalogSystemDisplayLabel(inboxItemSystemId(item), {
      vertical: item.vertical,
      systemLabel: item.system_label,
    }),
  )
}

function reminderMatchesItem(
  reminder: ConnectorReminder,
  item: Pick<NeedsAttentionItem, 'system' | 'system_id' | 'vertical'>,
): boolean {
  const system = inboxItemSystemId(item)
  if (system && reminder.system === system) return true
  const vertical = (item.vertical ?? '').trim()
  return Boolean(vertical && reminder.vertical_id === vertical && !system)
}

/**
 * Owner-language gate when matching is blocked on connect or refresh.
 * Labels are "Needs connection" / "Needs refresh" — never cassandra / CA DROP-as-system.
 */
export function inboxItemConnectorBlock(
  item: Pick<NeedsAttentionItem, 'system' | 'system_id' | 'system_label' | 'vertical'>,
  options?: {
    reminders?: ConnectorReminder[] | null
    gate?: MatchingConnectorGate | null
    matchingDetail?: InboxConnectorBlockDetail | null
  },
): InboxConnectorBlock | null {
  if (!itemHasConnectableSystem(item)) return null

  const system = inboxItemSystemId(item)
  const detail = options?.matchingDetail
  const stub =
    detail?.result_kind === 'sheet_stub' ||
    detail?.result_kind === 'saas_stub' ||
    detail?.matched_contacts_status === 'not_live'

  const reminders = (options?.reminders ?? []).filter((reminder) =>
    reminderMatchesItem(reminder, item),
  )
  if (reminders.some((reminder) => REFRESH_REMINDER_CODES.has(reminder.code))) {
    return { kind: 'needs_refresh', label: 'Needs refresh' }
  }
  if (reminders.some((reminder) => CONNECTION_REMINDER_CODES.has(reminder.code))) {
    return { kind: 'needs_connection', label: 'Needs connection' }
  }

  const gate = options?.gate
  if (gate?.blocked && (!gate.system || !system || gate.system === system)) {
    if (gate.displayStatus === 'needs_refresh' || gate.gateCode === 'upload_stale') {
      return { kind: 'needs_refresh', label: 'Needs refresh' }
    }
    if (gate.displayStatus === 'needs_setup' || gate.gateCode === 'wizard_incomplete') {
      return { kind: 'needs_connection', label: 'Needs connection' }
    }
    return { kind: 'needs_refresh', label: 'Needs refresh' }
  }

  if (stub) {
    return { kind: 'needs_connection', label: 'Needs connection' }
  }

  return null
}

/** Worst connector block across a batch — connection first, then refresh. */
export function inboxItemsConnectorBlock(
  items: Array<Pick<NeedsAttentionItem, 'system' | 'system_id' | 'system_label' | 'vertical'>>,
  options?: {
    reminders?: ConnectorReminder[] | null
    gate?: MatchingConnectorGate | null
  },
): InboxConnectorBlock | null {
  let refresh: InboxConnectorBlock | null = null
  for (const item of items) {
    const block = inboxItemConnectorBlock(item, options)
    if (block?.kind === 'needs_connection') return block
    if (block?.kind === 'needs_refresh') refresh = block
  }
  return refresh
}
