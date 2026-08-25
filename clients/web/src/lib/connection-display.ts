import type {
  ConnectorReminder,
  ConnectionDisplayStatus,
  ConnectionRecord,
  IntegrationSystemId,
  MatchingAttemptRow,
  MePayload,
  NeedsAttentionItem,
} from './api'

/** Upload-only systems — no Live credential invite (KD14). */
export const UPLOAD_ONLY_SYSTEMS: ReadonlySet<IntegrationSystemId> = new Set([
  'axios_headquarters',
  'bizdev_contacts',
  'hr_alumni',
])

const DISPLAY_STATUS_LABELS: Record<ConnectionDisplayStatus, string> = {
  needs_refresh: 'Needs refresh',
  action_required: 'Action required',
  needs_setup: 'Needs setup',
  connected: 'Connected',
  view_only: 'View only',
}

export type ConnectionStatusChipVariant = 'ok' | 'fail' | 'run' | 'wait' | 'default'

/** Prefer gated `display_status` (KD18) over raw connection `status`. */
export function resolveConnectionChipStatus(
  connection: Pick<ConnectionRecord, 'status' | 'display_status'>,
): string {
  const gated = connection.display_status?.trim()
  if (gated) return gated
  return connection.status
}

/** AE8 / KD18 human labels for gated display statuses. */
export function connectionDisplayStatusLabel(status: string | null | undefined): string {
  if (!status) return 'Unknown'
  const known = DISPLAY_STATUS_LABELS[status as ConnectionDisplayStatus]
  if (known) return known
  return status.replaceAll('_', ' ')
}

export function connectionDisplayStatusVariant(
  status: string | null | undefined,
): ConnectionStatusChipVariant {
  switch (status) {
    case 'connected':
      return 'ok'
    case 'view_only':
      return 'default'
    case 'needs_refresh':
    case 'action_required':
      return 'fail'
    case 'needs_setup':
    case 'pending':
    case 'infra_pending':
      return 'wait'
    case 'invited':
      return 'run'
    case 'failed':
    case 'revoked':
      return 'fail'
    default:
      return 'default'
  }
}

export function isUploadOnlySystem(system: string | null | undefined): boolean {
  return UPLOAD_ONLY_SYSTEMS.has(system as IntegrationSystemId)
}

/**
 * Ops invite minting — disabled for Cassandra, upload-only systems, and
 * systems with no credential fields (owner upload path instead).
 */
export function connectionInviteAllowed(options: {
  system?: string | null
  inviteAllowed?: boolean | null
  credentialFieldCount?: number | null
}): boolean {
  const system = options.system?.trim()
  if (!system || system === 'cassandra') return false
  if (isUploadOnlySystem(system)) return false
  if (options.inviteAllowed === false) return false
  if (options.credentialFieldCount != null && options.credentialFieldCount <= 0) {
    return false
  }
  return true
}

/** Hide retired Google Sheets and infra-only cassandra from new-connection pickers. */
export function isCreatableConnectionSystem(options: {
  system_id: string
  invite_allowed: boolean
}): boolean {
  if (options.system_id === 'google_sheets') return false
  if (options.system_id === 'cassandra') return false
  if (isUploadOnlySystem(options.system_id)) return true
  return options.invite_allowed
}

export type MatchingConnectorGateSource = 'attempt' | 'connection' | 'reminder'

/** KD18 / R52 — connector gate blocking matching for a vertical system. */
export type MatchingConnectorGate = {
  blocked: true
  displayStatus: string
  gateCode?: string | null
  system?: string | null
  source: MatchingConnectorGateSource
}

const MATCHING_HARD_GATE_REMINDER_CODES = new Set([
  'upload_stale',
  'rotation_overdue',
  'wizard_incomplete',
])

const CONNECTOR_ACTION_REMINDER_CODES = new Set([
  'upload_stale',
  'rotation_overdue',
  'wizard_incomplete',
])

/** Assigned vertical labels for owner Home — catalog names first, then ids. */
export function ownerAssignedVerticalSummary(
  labels?: { vertical_id: string; display_label: string }[] | null,
  verticals?: string[] | null,
): string {
  const named = (labels ?? [])
    .map((entry) => entry.display_label.trim())
    .filter(Boolean)
  if (named.length) return named.join(' · ')
  const ids = (verticals ?? [])
    .map((id) => id.trim().replaceAll('_', ' '))
    .filter(Boolean)
  if (ids.length) return ids.join(' · ')
  return 'No vertical assigned'
}

export type OwnerHomeQueueLane = 'matching' | 'fulfillment'

export type OwnerHomeQueueRow = {
  requestId: string
  title: string
  lane: OwnerHomeQueueLane
  receivedAt: string | null
  /** Matching-review item is per vertical — not request-level assignment. */
  vertical: string | null
  verticalLabel: string | null
}

export function ownerHomeItemTitle(
  item: Pick<NeedsAttentionItem, 'match_type'>,
  lane: OwnerHomeQueueLane,
): string {
  if (lane === 'fulfillment') return 'Fulfillment'
  if (item.match_type === 'single_match') return 'Confirm match'
  if (item.match_type === 'multi_match') return 'Multi-person'
  if (item.match_type === 'not_found') return 'Not a match'
  return 'Matching review'
}

/** Recent matching + fulfillment rows for owner Home — title first, newest first. */
export function ownerHomeQueueRows(options: {
  matching: NeedsAttentionItem[]
  fulfillment: NeedsAttentionItem[]
  limit?: number
}): OwnerHomeQueueRow[] {
  const limit = options.limit ?? 8
  const rows: OwnerHomeQueueRow[] = []
  for (const item of options.matching) {
    rows.push({
      requestId: item.request_id,
      title: ownerHomeItemTitle(item, 'matching'),
      lane: 'matching',
      receivedAt: item.received_at ?? item.requested_at,
      vertical: item.vertical ?? null,
      verticalLabel: item.vertical_label ?? null,
    })
  }
  for (const item of options.fulfillment) {
    rows.push({
      requestId: item.request_id,
      title: ownerHomeItemTitle(item, 'fulfillment'),
      lane: 'fulfillment',
      receivedAt: item.received_at ?? item.requested_at,
      vertical: item.vertical ?? null,
      verticalLabel: item.vertical_label ?? null,
    })
  }
  rows.sort((left, right) => {
    const leftTime = left.receivedAt ? Date.parse(left.receivedAt) : 0
    const rightTime = right.receivedAt ? Date.parse(right.receivedAt) : 0
    return rightTime - leftTime
  })
  return rows.slice(0, limit)
}

/** `/me` reminders + wizard flag — never invent a count when `me` is missing. */
export function ownerConnectorActionRequiredCount(
  me: Pick<MePayload, 'connector_reminders' | 'needs_connector_setup'> | null | undefined,
): number | null {
  if (!me) return null
  const reminders: ConnectorReminder[] = me.connector_reminders ?? []
  const fromReminders = reminders.filter(
    (reminder) =>
      reminder.severity === 'overdue' || CONNECTOR_ACTION_REMINDER_CODES.has(reminder.code),
  ).length
  const setupExtra =
    me.needs_connector_setup &&
    !reminders.some((reminder) => reminder.code === 'wizard_incomplete')
      ? 1
      : 0
  return fromReminders + setupExtra
}

const REMINDER_CODE_TO_DISPLAY_STATUS: Record<string, ConnectionDisplayStatus> = {
  upload_stale: 'needs_refresh',
  upload_approaching: 'needs_refresh',
  rotation_overdue: 'action_required',
  rotation_approaching: 'action_required',
  wizard_incomplete: 'action_required',
}

/** Display statuses that mean matching is hard-gated (never show Connected). */
export function isMatchingGateBlockedDisplayStatus(
  status: string | null | undefined,
): boolean {
  const normalized = (status ?? '').trim().toLowerCase()
  return (
    normalized === 'needs_refresh' ||
    normalized === 'action_required' ||
    normalized === 'needs_setup'
  )
}

function coerceAttemptAudit(payload: unknown): Record<string, unknown> {
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    return payload as Record<string, unknown>
  }
  return {}
}

/** Read gate fields from a matching attempt audit payload (gate_blocked terminal). */
export function matchingGateFromAttemptAudit(
  audit: Record<string, unknown>,
  attempt?: Pick<MatchingAttemptRow, 'error_code' | 'status'>,
): MatchingConnectorGate | null {
  const event = typeof audit.event === 'string' ? audit.event.trim() : ''
  const auditError =
    typeof audit.error_code === 'string' ? audit.error_code.trim() : ''
  const attemptError = attempt?.error_code?.trim() ?? ''
  const isGateBlocked =
    attemptError === 'gate_blocked' ||
    auditError === 'gate_blocked' ||
    event === 'gate_blocked' ||
    attempt?.status === 'gate_blocked'

  if (!isGateBlocked) return null

  const rawDisplay =
    typeof audit.display_status === 'string' ? audit.display_status.trim().toLowerCase() : ''
  const displayStatus = isMatchingGateBlockedDisplayStatus(rawDisplay)
    ? rawDisplay
    : 'action_required'
  const gateCode =
    typeof audit.gate_code === 'string'
      ? audit.gate_code
      : attemptError || auditError || 'gate_blocked'
  const blockingSystem =
    typeof audit.blocking_system === 'string' ? audit.blocking_system.trim() : ''
  const system =
    blockingSystem ||
    (typeof audit.system === 'string' ? audit.system.trim() : '') ||
    null

  return {
    blocked: true,
    displayStatus,
    gateCode,
    system,
    source: 'attempt',
  }
}

/** Latest attempt with gate_blocked audit wins (attempt_number descending). */
export function matchingGateFromAttempts(
  attempts: MatchingAttemptRow[] | null | undefined,
): MatchingConnectorGate | null {
  if (!attempts?.length) return null
  const sorted = [...attempts].sort((a, b) => b.attempt_number - a.attempt_number)
  for (const attempt of sorted) {
    const gate = matchingGateFromAttemptAudit(coerceAttemptAudit(attempt.audit_payload), attempt)
    if (gate) return gate
  }
  return null
}

export function matchingGateFromConnection(
  connection: Pick<
    ConnectionRecord,
    'system' | 'display_status' | 'gate_allowed' | 'gate_code' | 'status'
  >,
): MatchingConnectorGate | null {
  if (connection.gate_allowed !== false) return null
  const displayStatus = resolveConnectionChipStatus(connection)
  return {
    blocked: true,
    displayStatus: isMatchingGateBlockedDisplayStatus(displayStatus)
      ? displayStatus
      : 'action_required',
    gateCode: connection.gate_code,
    system: connection.system,
    source: 'connection',
  }
}

export function matchingGateFromConnections(
  connections: ConnectionRecord[] | null | undefined,
): MatchingConnectorGate | null {
  if (!connections?.length) return null
  for (const connection of connections) {
    const gate = matchingGateFromConnection(connection)
    if (gate) return gate
  }
  return null
}

export function matchingGateFromReminder(
  reminder: ConnectorReminder,
): MatchingConnectorGate | null {
  const hardGate =
    MATCHING_HARD_GATE_REMINDER_CODES.has(reminder.code) ||
    (reminder.severity === 'overdue' &&
      reminder.code !== 'upload_approaching' &&
      reminder.code !== 'rotation_approaching')
  if (!hardGate) return null

  const displayStatus =
    REMINDER_CODE_TO_DISPLAY_STATUS[reminder.code] ?? 'action_required'
  return {
    blocked: true,
    displayStatus,
    gateCode: reminder.code,
    system: reminder.system,
    source: 'reminder',
  }
}

export function matchingGateFromReminders(
  reminders: ConnectorReminder[] | null | undefined,
): MatchingConnectorGate | null {
  if (!reminders?.length) return null
  const priority = ['upload_stale', 'rotation_overdue', 'wizard_incomplete']
  for (const code of priority) {
    const reminder = reminders.find((entry) => entry.code === code)
    if (reminder) {
      const gate = matchingGateFromReminder(reminder)
      if (gate) return gate
    }
  }
  for (const reminder of reminders) {
    const gate = matchingGateFromReminder(reminder)
    if (gate) return gate
  }
  return null
}

/** Attempt audit first; then ops connections; then soft reminder payloads (R52). */
export function resolveMatchingConnectorGate(options: {
  attempts?: MatchingAttemptRow[] | null
  connections?: ConnectionRecord[] | null
  reminders?: ConnectorReminder[] | null
}): MatchingConnectorGate | null {
  const fromAttempts = matchingGateFromAttempts(options.attempts)
  if (fromAttempts) return fromAttempts
  const fromConnections = matchingGateFromConnections(options.connections)
  if (fromConnections) return fromConnections
  return matchingGateFromReminders(options.reminders)
}

export function matchingConnectorGateChip(gate: MatchingConnectorGate): {
  label: string
  variant: ConnectionStatusChipVariant
} {
  return {
    label: connectionDisplayStatusLabel(gate.displayStatus),
    variant: connectionDisplayStatusVariant(gate.displayStatus),
  }
}

export function matchingConnectorGateBannerCopy(gate: MatchingConnectorGate): {
  title: string
  description: string
} {
  const chip = matchingConnectorGateChip(gate)
  const systemLabel = gate.system?.replaceAll('_', ' ') ?? 'connector'
  if (gate.displayStatus === 'needs_setup' || gate.gateCode === 'wizard_incomplete') {
    return {
      title: `${chip.label} — matching gated`,
      description: `Connector setup for ${systemLabel} is incomplete. Matching stays gated until the owner finishes the wizard.`,
    }
  }
  if (gate.displayStatus === 'needs_refresh' || gate.gateCode === 'upload_stale') {
    return {
      title: `${chip.label} — matching gated`,
      description: `Upload data for ${systemLabel} is stale. Matching stays gated until the owner uploads a fresh file.`,
    }
  }
  if (gate.gateCode === 'rotation_overdue' || gate.displayStatus === 'action_required') {
    return {
      title: `${chip.label} — matching gated`,
      description: `Live credentials for ${systemLabel} need rotation. Matching stays gated until credentials are refreshed.`,
    }
  }
  return {
    title: `${chip.label} — matching gated`,
    description: `Matching for ${systemLabel} is blocked until the connector gate clears. A passing connection test does not enable matching.`,
  }
}

export function attemptIsGateBlocked(
  attempt: MatchingAttemptRow,
): MatchingConnectorGate | null {
  return matchingGateFromAttemptAudit(coerceAttemptAudit(attempt.audit_payload), attempt)
}

export function leverTriageCopy(detail: string | null | undefined): string | null {
  const code = detail?.trim().toLowerCase()
  if (code === 'lever_unauthorized') {
    return 'Lever triage: API key rejected (unauthorized). Confirm the Lever API key — not a password and not the Postings-only key.'
  }
  if (code === 'lever_forbidden') {
    return 'Lever triage: key accepted but Users access denied (forbidden). Enable Users read/list on the Lever API key and regenerate if permissions cannot be changed.'
  }
  return null
}

/** Catalog id for the view-only Data vertical (KD8 / KD20). */
export const DATA_CATALOG_VERTICAL_ID = 'data'

/** AE32 — Live-down overlay copy. No Ops invite language. */
export const OVERLAY_LIVE_DOWN_COPY =
  "Live isn't connected or permissioned — upload a file or retest in Connectors."

const LIVE_DOWN_ERROR_CODES = new Set([
  'gate_blocked',
  'auth_failed',
  'lever_unauthorized',
  'lever_forbidden',
  'test_failed',
  'live_test_failed',
  'not_permissioned',
  'permission_denied',
  'forbidden',
])

export type OverlayConnectorCallout = {
  title: string
  description: string
  displayStatus: string
  verticalId: string | null
  showCta: boolean
}

export function isDataCatalogVertical(verticalId: string | null | undefined): boolean {
  const id = (verticalId ?? '').trim().toLowerCase()
  return id === DATA_CATALOG_VERTICAL_ID || id === 'cassandra'
}

export function ownerConnectorsSearch(
  verticalId: string | null | undefined,
): { vertical?: string } {
  const id = verticalId?.trim()
  return id ? { vertical: id } : {}
}

/** Owner Connectors CTA — data_owner only; never for Data (view-only). */
export function overlayCalloutShowsOwnerCta(
  role: string | null | undefined,
  verticalId: string | null | undefined,
): boolean {
  return role === 'data_owner' && !isDataCatalogVertical(verticalId)
}

function overlayCalloutTitle(displayStatus: string): string {
  if (displayStatus === 'needs_refresh') {
    return connectionDisplayStatusLabel('needs_refresh')
  }
  return connectionDisplayStatusLabel('action_required')
}

function remindersForViewer(
  reminders: ConnectorReminder[] | null | undefined,
  assignedVerticals: readonly string[] | null | undefined,
): ConnectorReminder[] {
  if (!reminders?.length) return []
  const assigned = new Set(
    (assignedVerticals ?? []).map((id) => id.trim()).filter(Boolean),
  )
  if (assigned.size === 0) return [...reminders]
  return reminders.filter((reminder) => assigned.has(reminder.vertical_id))
}

function verticalIdFromAttempts(
  attempts: MatchingAttemptRow[] | null | undefined,
): string | null {
  if (!attempts?.length) return null
  const sorted = [...attempts].sort((a, b) => b.attempt_number - a.attempt_number)
  for (const attempt of sorted) {
    const raw = coerceAttemptAudit(attempt.audit_payload).vertical_id
    if (typeof raw === 'string' && raw.trim()) return raw.trim()
  }
  return null
}

function matchingGateFromLiveDownErrors(
  attempts: MatchingAttemptRow[] | null | undefined,
  extraCodes: readonly (string | null | undefined)[] | null | undefined,
): MatchingConnectorGate | null {
  const codes: string[] = []
  for (const attempt of attempts ?? []) {
    if (attempt.error_code) codes.push(attempt.error_code)
    const audit = coerceAttemptAudit(attempt.audit_payload)
    if (typeof audit.error_code === 'string') codes.push(audit.error_code)
    if (typeof audit.event === 'string') codes.push(audit.event)
    if (audit.last_test_ok === false) codes.push('live_test_failed')
  }
  for (const code of extraCodes ?? []) {
    if (code) codes.push(code)
  }
  for (const code of codes) {
    const normalized = code.trim().toLowerCase()
    const liveDown =
      LIVE_DOWN_ERROR_CODES.has(normalized) ||
      isMatchingGateBlockedDisplayStatus(normalized)
    if (!liveDown) continue
    return {
      blocked: true,
      displayStatus:
        normalized === 'needs_refresh' || normalized === 'upload_stale'
          ? 'needs_refresh'
          : 'action_required',
      gateCode: normalized,
      source: 'attempt',
    }
  }
  return null
}

function resolveCalloutVerticalId(options: {
  gate: MatchingConnectorGate
  reminders: ConnectorReminder[]
  attempts?: MatchingAttemptRow[] | null
  assignedVerticals?: readonly string[] | null
}): string | null {
  const fromReminder = options.reminders.find(
    (reminder) =>
      reminder.system === options.gate.system ||
      reminder.code === options.gate.gateCode,
  )
  if (fromReminder?.vertical_id) return fromReminder.vertical_id
  if (options.gate.system === 'cassandra') return DATA_CATALOG_VERTICAL_ID
  const fromAttempt = verticalIdFromAttempts(options.attempts)
  if (fromAttempt) return fromAttempt
  const assigned = (options.assignedVerticals ?? [])
    .map((id) => id.trim())
    .filter(Boolean)
  const nonData = assigned.filter((id) => !isDataCatalogVertical(id))
  if (nonData.length === 1) return nonData[0] ?? null
  if (assigned.length === 1) return assigned[0] ?? null
  return null
}

/**
 * Overlay Live-down / freshness callout (U19 / AE32 / KD18).
 * Uses matching attempts + `/me` reminders — no extra API.
 */
export function resolveOverlayConnectorCallout(options: {
  role?: string | null
  assignedVerticals?: readonly string[] | null
  reminders?: ConnectorReminder[] | null
  attempts?: MatchingAttemptRow[] | null
  journeyErrorCodes?: readonly (string | null | undefined)[] | null
}): OverlayConnectorCallout | null {
  const assigned = (options.assignedVerticals ?? [])
    .map((id) => id.trim())
    .filter(Boolean)
  const scopedReminders = remindersForViewer(options.reminders, assigned)
  const gate =
    resolveMatchingConnectorGate({
      attempts: options.attempts,
      reminders: scopedReminders,
    }) ?? matchingGateFromLiveDownErrors(options.attempts, options.journeyErrorCodes)
  if (!gate?.blocked) return null

  const verticalId = resolveCalloutVerticalId({
    gate,
    reminders: scopedReminders,
    attempts: options.attempts,
    assignedVerticals: assigned,
  })

  if (
    assigned.length > 0 &&
    verticalId &&
    !assigned.includes(verticalId) &&
    options.role === 'data_owner'
  ) {
    return null
  }

  const displayStatus =
    gate.displayStatus === 'needs_refresh' ? 'needs_refresh' : 'action_required'

  return {
    title: overlayCalloutTitle(displayStatus),
    description: OVERLAY_LIVE_DOWN_COPY,
    displayStatus,
    verticalId,
    showCta: overlayCalloutShowsOwnerCta(options.role, verticalId),
  }
}
