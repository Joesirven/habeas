/**
 * Owner connector wizard helpers — delimiter options, gated display status,
 * soft reminder banners (pure; no React).
 */

import type { ConnectorReminder, ConnectionDisplayStatus } from '@/lib/api'
import { PLATFORM_NAME } from './brand'

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

/** Reminder codes that are informational on the owner connectors page (wizard is the fix). */
export const OWNER_CONNECTORS_SUPPRESSED_REMINDER_CODES = new Set(['wizard_incomplete'])

/** Drop redundant reminders while the owner is on the connectors wizard surface. */
export function filterRemindersForOwnerConnectorsPage(
  reminders: ConnectorReminder[] | null | undefined,
): ConnectorReminder[] {
  if (!reminders?.length) return []
  return reminders.filter(
    (reminder) => !OWNER_CONNECTORS_SUPPRESSED_REMINDER_CODES.has(reminder.code),
  )
}

function reminderDisplaySeverity(
  reminder: ConnectorReminder,
): ConnectorReminder['severity'] {
  // wizard_incomplete is soft — never show as overdue/red (KD23 / demo UX).
  if (reminder.code === 'wizard_incomplete') return 'approaching'
  return reminder.severity
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
      severity: reminderDisplaySeverity(reminder),
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

/** KD28 — user-facing product name for owner connector copy. */
export { PLATFORM_NAME as HABEAS_PLATFORM_DISPLAY_NAME } from './brand'

export type ConnectorApproachMode = 'upload' | 'live'

export type ModeDefinitionCardCopy = {
  mode: ConnectorApproachMode
  title: string
  /** Plain-language definition for the always-visible explainer card. */
  definition: string
}

export const MODE_UPLOAD_DEFINITION_CARD: ModeDefinitionCardCopy = {
  mode: 'upload',
  title: 'Upload',
  definition: `You download our template, fill it with your export, and send the file to ${PLATFORM_NAME} on a refresh schedule you choose.`,
}

export const MODE_LIVE_DEFINITION_CARD: ModeDefinitionCardCopy = {
  mode: 'live',
  title: 'Live',
  definition: `${PLATFORM_NAME} connects directly to the service with credentials you provide and pulls updated data automatically.`,
}

/** KD25 — always-visible Upload vs Live definition cards (default copy). */
export const MODE_DEFINITION_CARDS: readonly ModeDefinitionCardCopy[] = [
  MODE_UPLOAD_DEFINITION_CARD,
  MODE_LIVE_DEFINITION_CARD,
]

/** KD25 / R17 — shared Mode-step footnote: connecting ≠ enabling matching. */
export const MODE_STEP_CONNECTING_NOT_MATCHING_FOOTNOTE =
  'Connecting a system does not start matching by itself. Matching runs only after you finish this wizard, keep data fresh on your cadence, and rotate Live credentials when due.'

export type ModeStepCardState = {
  mode: ConnectorApproachMode
  title: string
  definition: string
  /** Per-system one-line hint when this mode is allowed (KD25). */
  hint: string | null
  allowed: boolean
  /** Plain-language reason when the mode is greyed out (KD25). */
  disabledReason: string | null
}

const MODE_SYSTEM_HINTS: Record<
  string,
  Partial<Record<ConnectorApproachMode, string>>
> = {
  mailchimp: {
    upload:
      'Export your Mailchimp audience to our CSV template and upload on your refresh schedule.',
    live: 'Habeas pulls audience members from Mailchimp using an API key.',
  },
  paylocity: {
    upload:
      'Fill the Paylocity template CSV and upload on your cadence — no Developer Portal credentials needed.',
    live:
      'Paylocity will deliver employee files through SFTP (coming soon) — not an API connection.',
  },
  lever: {
    live:
      'Habeas pulls recruiting candidate data from Lever using an API key with Users read/list.',
  },
  auth0: {
    upload:
      'Export Auth0 user records to our template and upload on your refresh schedule.',
    live: 'Habeas pulls user records from Auth0 using Machine-to-Machine API credentials.',
  },
  bizdev_contacts: {
    upload:
      'Upload Contact Us shaped contacts using the Habeas CSV template on your refresh schedule.',
  },
  hr_alumni: {
    upload:
      'Upload your static alumni list using the Habeas CSV template on your refresh schedule.',
  },
}

const DISALLOWED_MODE_REASONS: Record<
  string,
  Partial<Record<ConnectorApproachMode, string>>
> = {
  bizdev_contacts: {
    live: 'BizDev Contacts is Upload only — there is no Live connection for this system.',
  },
  hr_alumni: {
    live: 'HR Alumni is Upload only — this is a static list, not a live feed.',
  },
  lever: {
    upload: 'Lever only supports Live — Habeas connects via the Lever API.',
  },
  paylocity: {
    live: 'Paylocity Live (SFTP) is not available yet. Use Upload with the Habeas template for now.',
  },
}

function normalizeSystemId(systemId: string): string {
  return systemId.trim().toLowerCase()
}

function displayLabel(displayName: string | undefined, systemId: string): string {
  const trimmed = (displayName ?? '').trim()
  if (trimmed) return trimmed
  return systemId.replaceAll('_', ' ')
}

/** Whether an approach mode is among the configured allowed approaches. */
export function isModeAllowed(
  mode: ConnectorApproachMode,
  allowedApproaches: readonly string[] | null | undefined,
): boolean {
  if (mode === 'upload') return allowsUpload(allowedApproaches)
  return allowsLive(allowedApproaches)
}

/** KD25 — Mode step intro for a system row. */
export function modeStepIntroCopy(displayName: string): string {
  return `Choose how ${PLATFORM_NAME} receives data for ${displayName}. Read both options below — you only need to pick one.`
}

function modeDefinitionForSystem(
  systemId: string,
  mode: ConnectorApproachMode,
): string {
  const normalized = normalizeSystemId(systemId)
  if (normalized === 'paylocity' && mode === 'live') {
    return `${PLATFORM_NAME} will receive Paylocity employee files through SFTP when Live is available (coming soon). This is not an API connection — use Upload today.`
  }
  const card = MODE_DEFINITION_CARDS.find((entry) => entry.mode === mode)
  return card?.definition ?? ''
}

/** KD25 — per-system one-line hint for an allowed mode. */
export function modeStepSystemHint(
  systemId: string,
  mode: ConnectorApproachMode,
): string | null {
  const hints = MODE_SYSTEM_HINTS[normalizeSystemId(systemId)]
  return hints?.[mode] ?? null
}

/** KD25 — plain-language reason when a mode is greyed out. */
export function disallowedModeReason(
  systemId: string,
  mode: ConnectorApproachMode,
  options?: { displayName?: string; allowedApproaches?: readonly string[] },
): string {
  const normalized = normalizeSystemId(systemId)
  const label = displayLabel(options?.displayName, normalized)
  const known = DISALLOWED_MODE_REASONS[normalized]?.[mode]
  if (known) return known
  if (options?.allowedApproaches && isModeAllowed(mode, options.allowedApproaches)) {
    return ''
  }
  if (mode === 'upload') {
    return `Upload is not available for ${label}.`
  }
  return `Live is not available for ${label}.`
}

/** KD25 — build Upload vs Live cards for the Mode wizard step. */
export function buildModeStepCards(input: {
  systemId: string
  displayName: string
  allowedApproaches: readonly string[]
}): ModeStepCardState[] {
  const normalized = normalizeSystemId(input.systemId)
  return MODE_DEFINITION_CARDS.map((card) => {
    const allowed = isModeAllowed(card.mode, input.allowedApproaches)
    return {
      mode: card.mode,
      title: card.title,
      definition: modeDefinitionForSystem(normalized, card.mode),
      hint: allowed ? modeStepSystemHint(normalized, card.mode) : null,
      allowed,
      disabledReason: allowed
        ? null
        : disallowedModeReason(normalized, card.mode, {
            displayName: input.displayName,
            allowedApproaches: input.allowedApproaches,
          }),
    }
  })
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

/** Live connect step is ready when credentials are stored and tested (matches _wizard_ready). */
export function liveConnectReady(input: {
  status?: string | null
  last_test_ok?: boolean | null
  metadata?: Record<string, unknown> | null
}): boolean {
  const rotated = input.metadata?.credentials_rotated_at
  if (typeof rotated === 'string' && rotated.trim()) return true
  if (input.last_test_ok) return true
  return input.status === 'connected'
}
