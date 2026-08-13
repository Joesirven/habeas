import type {
  ConnectionDisplayStatus,
  ConnectionRecord,
  IntegrationSystemId,
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
