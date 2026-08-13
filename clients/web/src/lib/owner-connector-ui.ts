/**
 * Owner connector wizard helpers — delimiter options, gated display status,
 * soft reminder banners (pure; no React).
 */

import type { ConnectorReminder, ConnectionDisplayStatus } from '@/lib/api'

/** AE10 / R19 — multi-PII delimiter choices for Upload. */
export type MultiPiiDelimiterOption = {
  /** Form / API value — `null` means one value per cell. */
  value: string | null
  /** Select option key (string form of value). */
  key: string
  label: string
}

export const MULTI_PII_DELIMITER_OPTIONS: readonly MultiPiiDelimiterOption[] = [
  { value: null, key: 'none', label: 'None (one value per cell)' },
  { value: ';', key: ';', label: ';' },
  { value: '|', key: '|', label: '|' },
  { value: ',', key: ',', label: ',' },
] as const

export function delimiterOptionFromKey(key: string): MultiPiiDelimiterOption {
  const found = MULTI_PII_DELIMITER_OPTIONS.find((opt) => opt.key === key)
  return found ?? MULTI_PII_DELIMITER_OPTIONS[0]
}

export function delimiterValueFromKey(key: string): string | null {
  return delimiterOptionFromKey(key).value
}

export type DisplayStatusChip = {
  label: string
  /** Badge variant used on owner / ops surfaces. */
  variant: 'ok' | 'fail' | 'run' | 'wait' | 'default'
}

const DISPLAY_STATUS_CHIPS: Record<ConnectionDisplayStatus, DisplayStatusChip> = {
  needs_setup: { label: 'Needs setup', variant: 'wait' },
  action_required: { label: 'Action required', variant: 'fail' },
  needs_refresh: { label: 'Needs refresh', variant: 'fail' },
  connected: { label: 'Connected', variant: 'ok' },
  view_only: { label: 'View only', variant: 'default' },
}

/**
 * Map API `display_status` to chip copy.
 * KD18: never show "Connected" when gate fails — prefer Needs refresh / Action required.
 */
export function displayStatusChip(
  displayStatus: string | null | undefined,
  options?: { gateAllowed?: boolean | null },
): DisplayStatusChip {
  const raw = (displayStatus ?? '').trim().toLowerCase()
  const gateAllowed = options?.gateAllowed

  if (gateAllowed === false) {
    if (raw === 'needs_refresh' || raw === 'action_required') {
      return DISPLAY_STATUS_CHIPS[raw]
    }
    if (raw === 'connected') {
      return DISPLAY_STATUS_CHIPS.needs_refresh
    }
    if (raw === 'needs_setup') {
      return DISPLAY_STATUS_CHIPS.needs_setup
    }
    return DISPLAY_STATUS_CHIPS.action_required
  }

  if (raw in DISPLAY_STATUS_CHIPS) {
    return DISPLAY_STATUS_CHIPS[raw as ConnectionDisplayStatus]
  }
  if (!raw) {
    return DISPLAY_STATUS_CHIPS.needs_setup
  }
  return { label: raw.replaceAll('_', ' '), variant: 'default' }
}

export type ReminderBannerItem = {
  id: string
  severity: ConnectorReminder['severity']
  title: string
  description: string
  verticalId: string
  system: string
}

const REMINDER_CODE_COPY: Record<string, { title: string; description: string }> = {
  upload_approaching: {
    title: 'Upload refresh coming due',
    description: 'Upload data for this system is approaching your cadence. Refresh soon so matching stays unblocked.',
  },
  upload_stale: {
    title: 'Upload refresh overdue',
    description: 'Upload data is past cadence. Matching stays gated until you upload a fresh file.',
  },
  wizard_incomplete: {
    title: 'Connector setup incomplete',
    description: 'Finish the connector wizard so matching can run for this system. This reminder does not block login.',
  },
  rotation_approaching: {
    title: 'Credential rotation coming due',
    description: 'Live credentials are approaching the rotation window. Rotate soon so matching stays unblocked.',
  },
  rotation_overdue: {
    title: 'Credential rotation overdue',
    description: 'Live credentials are past the rotation window. Matching stays gated until you rotate.',
  },
}

function fallbackReminderCopy(
  severity: ConnectorReminder['severity'],
  system: string,
): { title: string; description: string } {
  const systemLabel = system.replaceAll('_', ' ')
  if (severity === 'overdue') {
    return {
      title: `${systemLabel} needs attention`,
      description:
        'A connector refresh is overdue. Matching may stay gated until you update this system. This reminder does not block login.',
    }
  }
  return {
    title: `${systemLabel} refresh approaching`,
    description:
      'A connector refresh is coming due. Update soon so matching stays unblocked. This reminder does not block login.',
  }
}

/** Build non-blocking banner items from soft reminder payloads (R10 / KTD13). */
export function buildReminderBannerItems(
  reminders: ConnectorReminder[] | null | undefined,
): ReminderBannerItem[] {
  if (!reminders?.length) return []
  return reminders.map((reminder) => {
    const known = REMINDER_CODE_COPY[reminder.code]
    const copy = known ?? fallbackReminderCopy(reminder.severity, reminder.system)
    return {
      id: `${reminder.vertical_id}:${reminder.system}:${reminder.code}`,
      severity: reminder.severity,
      title: copy.title,
      description: copy.description,
      verticalId: reminder.vertical_id,
      system: reminder.system,
    }
  })
}

/** Filter out locally dismissed reminder ids (session-local dismiss). */
export function visibleReminderBanners(
  items: ReminderBannerItem[],
  dismissedIds: ReadonlySet<string> | readonly string[],
): ReminderBannerItem[] {
  const dismissed =
    dismissedIds instanceof Set ? dismissedIds : new Set(dismissedIds)
  return items.filter((item) => !dismissed.has(item.id))
}

export type OwnerWizardStep = 'mode' | 'connect' | 'cadence' | 'confirm'

export const OWNER_WIZARD_STEPS: { id: OwnerWizardStep; label: string }[] = [
  { id: 'mode', label: 'Mode' },
  { id: 'connect', label: 'Connect' },
  { id: 'cadence', label: 'Cadence' },
  { id: 'confirm', label: 'Confirm' },
]

export function ownerWizardStepIndex(step: OwnerWizardStep): number {
  return OWNER_WIZARD_STEPS.findIndex((entry) => entry.id === step)
}

/** Whether Upload approach is among allowed modes. */
export function allowsUpload(approaches: readonly string[] | null | undefined): boolean {
  return (approaches ?? []).includes('upload')
}

/** Whether Live approach is among allowed modes. */
export function allowsLive(approaches: readonly string[] | null | undefined): boolean {
  return (approaches ?? []).includes('live')
}

/** Default cadence days when metadata has none (matches core DEFAULT_UPLOAD_CADENCE_DAYS). */
export const DEFAULT_OWNER_CADENCE_DAYS = 30

export function cadenceDaysFromMetadata(
  metadata: Record<string, unknown> | null | undefined,
): number {
  if (!metadata) return DEFAULT_OWNER_CADENCE_DAYS
  const override = metadata.cadence_days_override
  if (typeof override === 'number' && Number.isFinite(override) && override >= 1) {
    return Math.floor(override)
  }
  if (typeof override === 'string' && override.trim()) {
    const parsed = Number.parseInt(override.trim(), 10)
    if (Number.isFinite(parsed) && parsed >= 1) return parsed
  }
  const cadence = metadata.cadence_days
  if (typeof cadence === 'number' && Number.isFinite(cadence) && cadence >= 1) {
    return Math.floor(cadence)
  }
  if (typeof cadence === 'string' && cadence.trim()) {
    const parsed = Number.parseInt(cadence.trim(), 10)
    if (Number.isFinite(parsed) && parsed >= 1) return parsed
  }
  return DEFAULT_OWNER_CADENCE_DAYS
}

export function activeModeFromMetadata(
  metadata: Record<string, unknown> | null | undefined,
): 'live' | 'upload' | null {
  const mode = metadata?.active_mode
  if (mode === 'live' || mode === 'upload') return mode
  return null
}

/** Live connect step is ready when invite redeem has rotated credentials or connected. */
export function liveConnectReady(input: {
  status?: string | null
  metadata?: Record<string, unknown> | null
}): boolean {
  const rotated = input.metadata?.credentials_rotated_at
  if (typeof rotated === 'string' && rotated.trim()) return true
  return input.status === 'connected'
}
