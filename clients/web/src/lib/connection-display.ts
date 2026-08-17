import type {
  ConnectorReminder,
  ConnectionDisplayStatus,
  ConnectionRecord,
  IntegrationSystemId,
  MatchingAttemptRow,
} from './api'

/** Upload-only systems — no Live credential invite (KD14). */
export const UPLOAD_ONLY_SYSTEMS: ReadonlySet<IntegrationSystemId> = new Set([
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

/** Hide retired Google Sheets from new-connection pickers. */
export function isCreatableConnectionSystem(options: {
  system_id: string
  invite_allowed: boolean
}): boolean {
  if (options.system_id === 'google_sheets') return false
  if (options.system_id === 'cassandra') return true
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
