/**
 * Inbox batch-status grouping — match result / DROP disposition labels shared with
 * `/requests/needs-attention` Result chips and batch stacks.
 */

import type {
  ConnectorReminder,
  NeedsAttentionItem,
} from '@/lib/api'
import {
  matchingConnectorGateBannerCopy,
  matchingConnectorGateChip,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import { buildReminderBannerItems } from '@/lib/owner-connector-ui'

/** Status bucket for inbox stacks — mirrors Result filter + DROP codes 3/4/5. */
export type InboxBatchStatusKey =
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

/** Derive the batch-status bucket for an inbox row (match type or DROP 3/4/5). */
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

/** Same labels as inbox Result chips / DROP status pills. */
export function inboxBatchStatusLabel(
  key: InboxBatchStatusKey,
  ownerLanguage = false,
): string {
  switch (key) {
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

export type InboxBatchStatusSection = {
  key: InboxBatchStatusKey
  label: string
  items: NeedsAttentionItem[]
}

/** Group inbox items by batch-status type (stable sort order). */
export function groupInboxItemsByBatchStatus(
  items: NeedsAttentionItem[],
  ownerLanguage = false,
): InboxBatchStatusSection[] {
  const buckets = new Map<InboxBatchStatusKey, NeedsAttentionItem[]>()
  for (const item of items) {
    const key = inboxBatchStatusKey(item)
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

export type InboxBatchParts = { key: string; label: string }

export type InboxBatchStatusCrossGroup = {
  batchKey: string
  batchLabel: string
  statusKey: InboxBatchStatusKey
  statusLabel: string
  compositeKey: string
  items: NeedsAttentionItem[]
}

/** One stack per (batch, batch-status type) — e.g. #42 · Single match. */
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
