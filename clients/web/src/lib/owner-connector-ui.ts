/**
 * Owner connector wizard helpers — delimiter options, gated display status,
 * soft reminder banners, live-connect mapping follow-on (pure; no React).
 */

import type { ConnectorReminder, ConnectionDisplayStatus, OwnerConnectorSystem } from '@/lib/api'
import { catalogSystemDisplayLabel } from './legalJourneyLabels'
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
  sheets_refresh_stale: {
    title: 'Google Sheet refresh needed',
    description:
      'A new intake batch arrived. Refresh this source if it has been at least 12 hours since the last successful refresh so matching can run. Login is not blocked.',
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
    (reminder) =>
      !OWNER_CONNECTORS_SUPPRESSED_REMINDER_CODES.has(reminder.code) &&
      !isOwnerWizardHiddenSystem(reminder.system),
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

export type VerticalWizardStep = {
  id: string
  label?: string
}

export type VerticalWizardSystemInput = {
  system: string
  allowedApproaches: string[]
  displayLabel?: string
  /**
   * Include mapping after connect (sheets `mapping-clean`) or after live-creds
   * (Lever / Paylocity `{system}-mapping` when upload is allowed).
   * Defaults to true. Pass false when columns already map and no rows need cleaning.
   */
  needsMappingClean?: boolean
}

export type BuildVerticalWizardStepsArgs = {
  systems: VerticalWizardSystemInput[]
  viewOnly?: boolean
}

/** Alumni / Contact Us Google Sheets — owner OAuth or upload, not SA-share. */
export const SHEETS_OWNER_SYSTEM_IDS = ['hr_alumni', 'bizdev_contacts'] as const

export type SheetsOwnerSystemId = (typeof SHEETS_OWNER_SYSTEM_IDS)[number]

export const SHEETS_CONNECT_METHODS = ['oauth', 'upload'] as const

export type SheetsConnectMethod = (typeof SHEETS_CONNECT_METHODS)[number]

export function isSheetsOwnerSystem(system: string | null | undefined): boolean {
  const normalized = normalizeSystemId(system ?? '')
  return (
    normalized === 'hr_alumni' ||
    normalized === 'bizdev_contacts'
  )
}

/** Whether mapping/clean should follow the sheets connect step. */
export function shouldIncludeSheetsMappingClean(input?: {
  mapping?: Record<string, string> | null
  mappingComplete?: boolean
  rejectedRowCount?: number
}): boolean {
  if (!input) return true
  const complete =
    input.mappingComplete ??
    (input.mapping ? uploadMappingComplete(input.mapping) : false)
  const rejects = input.rejectedRowCount ?? 0
  return !complete || rejects > 0
}

/**
 * Live ping is connectivity only — not a hashed extract (Wave M S01/S02).
 * Matching still needs a mapped upload. Auth0 live extract is not in this set.
 */
export const LIVE_PING_NOT_EXTRACT_SYSTEMS = ['lever', 'paylocity'] as const

export type LivePingNotExtractSystemId =
  (typeof LIVE_PING_NOT_EXTRACT_SYSTEMS)[number]

export function livePingIsNotMatchingExtract(
  system: string | null | undefined,
): boolean {
  const normalized = normalizeSystemId(system ?? '')
  return (
    normalized === 'lever' ||
    normalized === 'paylocity'
  )
}

export function liveMappingFollowOnStepId(system: string): string {
  return `${normalizeSystemId(system)}-mapping`
}

export function liveUploadFallbackStepId(system: string): string {
  return `${normalizeSystemId(system)}-howto-upload`
}

/**
 * After live-creds, include `{system}-mapping` when upload is allowed and the
 * Live ping is not a matching extract (reuse sheets mapping completeness).
 */
export function shouldIncludeLiveMappingFollowOn(input: {
  system: string
  allowedApproaches: readonly string[] | null | undefined
  needsMappingClean?: boolean
  mapping?: Record<string, string> | null
  mappingComplete?: boolean
  rejectedRowCount?: number
}): boolean {
  const normalized = normalizeSystemId(input.system)
  if (isSheetsOwnerSystem(normalized)) return false
  if (isOwnerWizardHiddenSystem(normalized)) return false
  if (!livePingIsNotMatchingExtract(normalized)) return false
  if (!allowsUpload(input.allowedApproaches)) return false
  if (!(allowsLive(input.allowedApproaches) || allowsOauth(input.allowedApproaches))) {
    return false
  }
  if (input.needsMappingClean === false) return false
  if (input.needsMappingClean === true) return true
  return shouldIncludeSheetsMappingClean({
    mapping: input.mapping,
    mappingComplete: input.mappingComplete,
    rejectedRowCount: input.rejectedRowCount,
  })
}

export const LIVE_CONNECT_RETRY_LABEL = 'Retry connection'
export const LIVE_CONNECT_SETUP_UPLOAD_LABEL = 'Set up manual upload'

export const LIVE_CONNECT_SUCCESS_MAPPING_HINT =
  'Connection confirmed. Next, map identifier columns if the headers differ. Email or phone is enough. A Live test does not start matching by itself.'

/** Auth0 Live extract — after a passing test, go to cadence / Complete, not Upload. */
export const LIVE_CONNECT_SUCCESS_CONTINUE_HINT =
  'Connection confirmed. Continue to choose a refresh cadence, then complete the wizard. A Live test does not start matching by itself.'

export const LIVE_CONNECT_FAILURE_HINT =
  'Connection test failed. Retry the connection, or set up a manual upload and map identifier columns if the headers differ. Email or phone is enough.'

export const LIVE_CONNECT_FAILURE_RETRY_ONLY_HINT =
  'Connection test failed. Retry the connection.'

export const LIVE_PING_NOT_EXTRACT_HINT =
  'A successful Live test only checks connectivity. Matching still needs a mapped upload. Map identifier columns if the headers differ — email or phone is enough.'

export type LiveConnectUploadFallback = {
  label: string
  stepId: string
}

export type LiveConnectFailureActions = {
  retryLabel: string
  setupManualUpload: LiveConnectUploadFallback | null
  hint: string
}

export type LiveConnectSuccessFollowOn = {
  /** Wizard step after a passing Live test — mapping when upload is allowed. */
  nextStepId: string | null
  nextKind: 'mapping' | 'howto-upload' | 'continue'
  hint: string
  /** Still offer upload because Live ping is not extract (Lever / Paylocity). */
  setupManualUpload: LiveConnectUploadFallback | null
}

/**
 * Show Retry / Set up manual upload when Live fails and upload is allowed.
 * Cassandra never offers upload.
 */
export function liveConnectOffersUploadFallback(
  allowedApproaches: readonly string[] | null | undefined,
  system?: string | null,
): boolean {
  if (system && isOwnerWizardHiddenSystem(system)) return false
  return allowsUpload(allowedApproaches)
}

/** Live-fail CTAs: always Retry; Set up manual upload only when upload is allowed. */
export function liveConnectFailureActions(input: {
  system: string
  allowedApproaches: readonly string[] | null | undefined
}): LiveConnectFailureActions {
  const normalized = normalizeSystemId(input.system)
  const canUpload = liveConnectOffersUploadFallback(
    input.allowedApproaches,
    normalized,
  )
  return {
    retryLabel: LIVE_CONNECT_RETRY_LABEL,
    setupManualUpload: canUpload
      ? {
          label: LIVE_CONNECT_SETUP_UPLOAD_LABEL,
          stepId: liveUploadFallbackStepId(normalized),
        }
      : null,
    hint: canUpload
      ? LIVE_CONNECT_FAILURE_HINT
      : LIVE_CONNECT_FAILURE_RETRY_ONLY_HINT,
  }
}

/**
 * After a passing Live test: continue to mapping when that follow-on is in
 * the wizard; otherwise the next linear step. Lever/Paylocity still expose
 * Set up manual upload because the ping is not a hashed extract.
 */
export function liveConnectSuccessFollowOn(input: {
  system: string
  allowedApproaches: readonly string[] | null | undefined
  needsMappingClean?: boolean
  mapping?: Record<string, string> | null
  mappingComplete?: boolean
  rejectedRowCount?: number
}): LiveConnectSuccessFollowOn {
  const normalized = normalizeSystemId(input.system)
  const includeMapping = shouldIncludeLiveMappingFollowOn({
    system: normalized,
    allowedApproaches: input.allowedApproaches,
    needsMappingClean: input.needsMappingClean,
    mapping: input.mapping,
    mappingComplete: input.mappingComplete,
    rejectedRowCount: input.rejectedRowCount,
  })
  const canUpload = liveConnectOffersUploadFallback(
    input.allowedApproaches,
    normalized,
  )
  const pingOnly = livePingIsNotMatchingExtract(normalized)
  const setupManualUpload =
    canUpload && pingOnly
      ? {
          label: LIVE_CONNECT_SETUP_UPLOAD_LABEL,
          stepId: liveUploadFallbackStepId(normalized),
        }
      : null

  if (includeMapping) {
    return {
      nextStepId: liveMappingFollowOnStepId(normalized),
      nextKind: 'mapping',
      hint: pingOnly
        ? LIVE_PING_NOT_EXTRACT_HINT
        : LIVE_CONNECT_SUCCESS_MAPPING_HINT,
      setupManualUpload,
    }
  }
  // Ping-only Live (Lever / Paylocity) may still walk Upload. Auth0 Live is a
  // matching extract — do not send a passing test to Upload how-to.
  if (canUpload && pingOnly) {
    return {
      nextStepId: liveUploadFallbackStepId(normalized),
      nextKind: 'howto-upload',
      hint: LIVE_PING_NOT_EXTRACT_HINT,
      setupManualUpload,
    }
  }
  return {
    nextStepId: null,
    nextKind: 'continue',
    hint: pingOnly
      ? LIVE_PING_NOT_EXTRACT_HINT
      : LIVE_CONNECT_SUCCESS_CONTINUE_HINT,
    setupManualUpload,
  }
}

const LIVE_SUCCESS_SKIP_STEP_KINDS = new Set(['howto-upload', 'upload'])

/**
 * After a passing Auth0 (live-extract) test, skip that system's Upload how-to
 * and Upload steps. Next is cadence, confirm, or the following system.
 * Returns null for ping-only systems (Lever / Paylocity) — those use mapping.
 */
export function nextWizardStepAfterSuccessfulLive(
  steps: readonly VerticalWizardStep[],
  system: string,
): string | null {
  const normalized = normalizeSystemId(system)
  if (livePingIsNotMatchingExtract(normalized)) return null
  const liveCredsId = `${normalized}-live-creds`
  const start = verticalWizardStepIndex(steps, liveCredsId)
  const from = start >= 0 ? start + 1 : 0
  for (let i = from; i < steps.length; i += 1) {
    const parsed = parseVerticalWizardStepId(steps[i].id)
    if (
      parsed &&
      'system' in parsed &&
      parsed.system === normalized &&
      LIVE_SUCCESS_SKIP_STEP_KINDS.has(parsed.kind)
    ) {
      continue
    }
    return steps[i].id
  }
  return null
}

export function mappingFollowOnCopy(displayName: string): {
  title: string
  intro: string
} {
  const label = (displayName ?? '').trim() || 'this system'
  return {
    title: `Map columns for ${label}`,
    intro: `Map identifier columns if the headers differ. Email or phone is enough. A Live connection does not skip this step.`,
  }
}

const WIZARD_STEP_SUFFIXES = [
  'mapping-clean',
  'howto-upload',
  'howto-live',
  'live-creds',
  'connect',
  'mapping',
  'upload',
  'howto',
  'oauth',
  'clean',
] as const

export type ParsedVerticalWizardStep =
  | { kind: (typeof WIZARD_STEP_SUFFIXES)[number]; system: string }
  | { kind: 'cadence' }
  | { kind: 'confirm' }

/** Parse a linear wizard step id. Longer suffixes first so `hr_alumni-howto-upload` is not `upload`. */
export function parseVerticalWizardStepId(
  stepId: string,
): ParsedVerticalWizardStep | null {
  if (stepId === 'cadence') return { kind: 'cadence' }
  if (stepId === 'confirm') return { kind: 'confirm' }
  for (const suffix of WIZARD_STEP_SUFFIXES) {
    const needle = `-${suffix}`
    if (stepId.endsWith(needle) && stepId.length > needle.length) {
      return {
        kind: suffix,
        system: stepId.slice(0, -needle.length),
      }
    }
  }
  return null
}

function sheetsWizardSystemSteps(
  system: string,
  needsMappingClean: boolean,
): VerticalWizardStep[] {
  const steps: VerticalWizardStep[] = [
    { id: `${system}-howto` },
    { id: `${system}-connect` },
  ]
  if (needsMappingClean) {
    steps.push({ id: `${system}-mapping-clean` })
  }
  return steps
}

function wizardSystemStepsForBinding(
  system: string,
  allowedApproaches: readonly string[],
  options?: { needsMappingClean?: boolean },
): VerticalWizardStep[] {
  const normalized = normalizeSystemId(system)
  if (isSheetsOwnerSystem(normalized)) {
    return sheetsWizardSystemSteps(
      normalized,
      options?.needsMappingClean !== false,
    )
  }
  const steps: VerticalWizardStep[] = []
  if (allowsLive(allowedApproaches) || allowsOauth(allowedApproaches)) {
    steps.push({ id: `${normalized}-howto-live` })
    steps.push({ id: `${normalized}-live-creds` })
    if (
      shouldIncludeLiveMappingFollowOn({
        system: normalized,
        allowedApproaches,
        needsMappingClean: options?.needsMappingClean,
      })
    ) {
      steps.push({ id: liveMappingFollowOnStepId(normalized) })
    }
  }
  if (allowsUpload(allowedApproaches)) {
    steps.push({ id: `${normalized}-howto-upload` })
    steps.push({ id: `${normalized}-upload` })
  }
  return steps
}

function shouldIncludeWizardSystem(
  system: string,
  allowedApproaches: readonly string[],
): boolean {
  if (isOwnerWizardHiddenSystem(system)) return false
  if (isSheetsOwnerSystem(system)) return true
  if (!allowedApproaches.length) return false
  return (
    allowsUpload(allowedApproaches) ||
    allowsLive(allowedApproaches) ||
    allowsOauth(allowedApproaches)
  )
}

/** Build per-vertical linear wizard steps (one cadence + confirm after all systems). */
export function buildVerticalWizardSteps(
  args: BuildVerticalWizardStepsArgs,
): VerticalWizardStep[] {
  if (args.viewOnly) return []
  const steps: VerticalWizardStep[] = []
  for (const entry of args.systems) {
    if (!shouldIncludeWizardSystem(entry.system, entry.allowedApproaches)) continue
    steps.push(
      ...wizardSystemStepsForBinding(entry.system, entry.allowedApproaches, {
        needsMappingClean: entry.needsMappingClean,
      }),
    )
  }
  steps.push({ id: 'cadence' })
  steps.push({ id: 'confirm' })
  return steps
}

export function verticalWizardStepIndex(
  steps: readonly VerticalWizardStep[],
  stepId: string,
): number {
  return steps.findIndex((entry) => entry.id === stepId)
}

/** Progress bar fill 0–100 for the current step index and total step count. */
export function wizardProgressPercent(currentIndex: number, total: number): number {
  if (total <= 0) return 0
  if (currentIndex < 0) return 0
  const bounded = Math.min(currentIndex, total - 1)
  const pct = Math.round(((bounded + 1) / total) * 100)
  return Math.min(100, Math.max(0, pct))
}

export const CADENCE_OPTION_RARELY = 'rarely' as const
export const CADENCE_OPTION_WITH_NEW_BATCHES = 'with_new_batches' as const
export const CADENCE_OPTION_WEEKLY = 'weekly' as const

export const CADENCE_OPTION_IDS = [
  CADENCE_OPTION_RARELY,
  CADENCE_OPTION_WITH_NEW_BATCHES,
  CADENCE_OPTION_WEEKLY,
] as const

export type CadenceOptionId = (typeof CADENCE_OPTION_IDS)[number]

/** Sheets cadence is static (`rarely`) vs volatile (`with_new_batches`) only. */
export const SHEETS_CADENCE_OPTION_IDS = [
  CADENCE_OPTION_RARELY,
  CADENCE_OPTION_WITH_NEW_BATCHES,
] as const

export type SheetsCadenceOptionId = (typeof SHEETS_CADENCE_OPTION_IDS)[number]

/** Cadence ids for a wizard: sheets-only verticals omit weekly. */
export function cadenceOptionIdsForSystems(
  systems: readonly string[] | null | undefined,
): readonly CadenceOptionId[] {
  const ids = (systems ?? [])
    .map((system) => normalizeSystemId(system))
    .filter((system) => system.length > 0)
  if (ids.length > 0 && ids.every((system) => isSheetsOwnerSystem(system))) {
    return SHEETS_CADENCE_OPTION_IDS
  }
  return CADENCE_OPTION_IDS
}

/** Map persisted `refresh_policy` to owner-facing cadence option ids. */
export function cadenceOptionFromRefreshPolicy(
  policy: 'static' | 'volatile' | null | undefined,
): CadenceOptionId | null {
  if (policy === 'static') return CADENCE_OPTION_RARELY
  if (policy === 'volatile') return CADENCE_OPTION_WITH_NEW_BATCHES
  return null
}

/** Map cadence option id back to API `refresh_policy` when applicable. */
export function refreshPolicyFromCadenceOption(
  option: CadenceOptionId | null | undefined,
): 'static' | 'volatile' | null {
  if (option === CADENCE_OPTION_RARELY) return 'static'
  if (option === CADENCE_OPTION_WITH_NEW_BATCHES) return 'volatile'
  return null
}

/** Map cadence option id to API `refresh_cadence` string for writes. */
export function refreshCadenceFromCadenceOption(
  option: CadenceOptionId | null | undefined,
): CadenceOptionId | null {
  if (
    option === CADENCE_OPTION_RARELY ||
    option === CADENCE_OPTION_WITH_NEW_BATCHES ||
    option === CADENCE_OPTION_WEEKLY
  ) {
    return option
  }
  return null
}

function parseRefreshCadenceFromMetadata(
  metadata: Record<string, unknown> | null | undefined,
): CadenceOptionId | null {
  const raw = metadata?.refresh_cadence
  if (typeof raw === 'string') {
    const cadence = raw.trim().toLowerCase()
    if (cadence === CADENCE_OPTION_RARELY) return CADENCE_OPTION_RARELY
    if (cadence === CADENCE_OPTION_WITH_NEW_BATCHES) {
      return CADENCE_OPTION_WITH_NEW_BATCHES
    }
    if (cadence === CADENCE_OPTION_WEEKLY) return CADENCE_OPTION_WEEKLY
  }
  return cadenceOptionFromRefreshPolicy(refreshPolicyFromMetadata(metadata))
}

export function cadenceOptionFromMetadata(
  metadata: Record<string, unknown> | null | undefined,
): CadenceOptionId | null {
  return parseRefreshCadenceFromMetadata(metadata)
}

export type SystemWizardCopy = {
  uploadHowto?: string
  liveHowto?: string
  oauthHowto?: string
  /** Combined howto for sheets connect (OAuth or upload). */
  howto?: string
}

/** Per-system how-to copy for upload / live / sheets wizard substeps. */
export const SYSTEM_COPY: Record<string, SystemWizardCopy> = {
  axios_hq: {
    uploadHowto:
      'Export a contact or subscriber list from Axios HQ as CSV. Upload a fresh file every batch, then map identifier columns if the headers differ. Email or phone is enough. Habeas does not connect to Axios HQ directly.',
  },
  hr_alumni: {
    howto:
      'Connect the Alumni Google Sheet with Google OAuth, or upload a CSV if you cannot grant sheet access. Map identifier columns if the headers differ — email or phone is enough — then choose how often this list should stay current.',
    oauthHowto:
      'Sign in with Google (OAuth) to grant Habeas access to the Alumni sheet, then paste the spreadsheet URL. Habeas tests metadata access before you continue.',
    uploadHowto:
      'If Google OAuth is not available, upload the alumni list as CSV and map identifier columns if the headers differ. Email or phone is enough.',
  },
  bizdev_contacts: {
    howto:
      'Connect the Contact Us Google Sheet with Google OAuth, or upload a CSV if you cannot grant sheet access. Map identifier columns if the headers differ — email or phone is enough — then choose how often this list should stay current.',
    oauthHowto:
      'Sign in with Google (OAuth) to grant Habeas access to the Contact Us sheet, then paste the spreadsheet URL. Habeas tests metadata access before you continue.',
    uploadHowto:
      'If Google OAuth is not available, upload Contact Us rows as CSV and map identifier columns if the headers differ. Email or phone is enough.',
  },
  alumni_google_sheet: {
    liveHowto:
      'Sign in with Google to grant Habeas access to the Alumni sheet, then paste the spreadsheet URL. Sharing with a service account is not required.',
    uploadHowto:
      'If Google OAuth is not available, upload the alumni list as CSV and map identifier columns if the headers differ. Email or phone is enough.',
  },
  contact_us_google_sheet: {
    liveHowto:
      'Sign in with Google to grant Habeas access to the Contact Us sheet, then paste the spreadsheet URL. Sharing with a service account is not required.',
    uploadHowto:
      'If Google OAuth is not available, upload Contact Us rows as CSV and map identifier columns if the headers differ. Email or phone is enough.',
  },
  paylocity: {
    liveHowto:
      'Follow the numbered steps under each field to create Paylocity SFTP credentials, paste them, then run a connection test. Live is SFTP, not an API. If the test fails, retry the connection or set up a manual upload.',
    uploadHowto:
      'If Live credentials fail, upload a Paylocity CSV and map identifier columns if the headers differ. Email or phone is enough.',
  },
  lever: {
    liveHowto:
      'Follow the numbered steps to create a Lever API key, paste it, then run a connection test. A passing test only checks Users read/list — it does not extract candidates. If Live fails, retry the connection or set up a manual upload.',
    uploadHowto:
      'Export a CSV, then map identifier columns if the headers differ. Email or phone is enough.',
  },
  auth0: {
    liveHowto:
      'Follow the numbered steps to create an Auth0 Machine-to-Machine app, paste Domain, Client ID, and Client Secret, then run a connection test.',
    uploadHowto:
      'If Live credentials fail, export Auth0 users as CSV, upload, then map identifier columns if the headers differ. Email or phone is enough.',
  },
}

/** Whether Upload approach is among allowed modes. */
export function allowsUpload(approaches: readonly string[] | null | undefined): boolean {
  return (approaches ?? []).includes('upload')
}

/** Whether Live approach is among allowed modes. */
export function allowsLive(approaches: readonly string[] | null | undefined): boolean {
  return (approaches ?? []).includes('live')
}

/** Whether Google OAuth is among allowed modes (sheets connect). */
export function allowsOauth(approaches: readonly string[] | null | undefined): boolean {
  return (approaches ?? []).includes('oauth')
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
  definition: `You upload your existing export to ${PLATFORM_NAME}, then map identifier columns if the headers differ. Email or phone is enough.`,
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
  paylocity: {
    upload:
      'Upload a Paylocity export and map identifier columns if the headers differ. Email or phone is enough — no Developer Portal credentials needed.',
    live:
      'Paylocity will deliver employee files through SFTP — not an API connection. If Live fails, set up a manual upload.',
  },
  lever: {
    upload:
      'Export a CSV, then map identifier columns if the headers differ. Email or phone is enough. Habeas does not invent Lever column names.',
    live:
      'Habeas tests Lever with an API key that has Users read/list. A passing ping is not candidate matching — map an upload next.',
  },
  auth0: {
    upload:
      'Export Auth0 users as CSV, upload the file, then map identifier columns if the headers differ. Email or phone is enough.',
    live: 'Habeas pulls user records from Auth0 using Machine-to-Machine API credentials.',
  },
  bizdev_contacts: {
    upload:
      'Upload Contact Us contacts as CSV, then map identifier columns if the headers differ. Email or phone is enough.',
    live:
      'Connect the Contact Us Google Sheet with Google OAuth. Habeas does not use a service-account share.',
  },
  hr_alumni: {
    upload:
      'Upload your alumni list as CSV, then map identifier columns if the headers differ. Email or phone is enough.',
    live:
      'Connect the Alumni Google Sheet with Google OAuth. Habeas does not use a service-account share.',
  },
}

const DISALLOWED_MODE_REASONS: Record<
  string,
  Partial<Record<ConnectorApproachMode, string>>
> = {
  paylocity: {
    live:
      'Paylocity Live uses SFTP. When Live is not configured, use Upload and map identifier columns if the headers differ. Email or phone is enough.',
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
  systemId?: string | null,
): boolean {
  if (systemId && isSheetsOwnerSystem(systemId)) return true
  if (mode === 'upload') return allowsUpload(allowedApproaches)
  return allowsLive(allowedApproaches) || allowsOauth(allowedApproaches)
}

/** KD25 — Mode step intro for a system row. */
export function modeStepIntroCopy(displayName: string): string {
  return `Choose how ${PLATFORM_NAME} receives data for ${displayName}. Read both options below — you only need to pick one.`
}

function modeDefinitionForSystem(
  systemId: string,
  mode: ConnectorApproachMode,
  allowedApproaches?: readonly string[],
): string {
  const normalized = normalizeSystemId(systemId)
  if (normalized === 'paylocity' && mode === 'live') {
    const liveAllowed = allowedApproaches
      ? isModeAllowed('live', allowedApproaches, normalized)
      : false
    if (liveAllowed) {
      return `${PLATFORM_NAME} will receive Paylocity employee files through SFTP. This is not an API connection. If Live fails, retry the connection or set up a manual upload.`
    }
    return `${PLATFORM_NAME} will receive Paylocity employee files through SFTP. This is not an API connection — use Upload today.`
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
  if (isSheetsOwnerSystem(normalized)) return ''
  const known = DISALLOWED_MODE_REASONS[normalized]?.[mode]
  if (known) return known
  if (
    options?.allowedApproaches &&
    isModeAllowed(mode, options.allowedApproaches, normalized)
  ) {
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
    const allowed = isModeAllowed(card.mode, input.allowedApproaches, normalized)
    return {
      mode: card.mode,
      title: card.title,
      definition: modeDefinitionForSystem(
        normalized,
        card.mode,
        input.allowedApproaches,
      ),
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

export function refreshPolicyFromMetadata(
  metadata: Record<string, unknown> | null | undefined,
): 'static' | 'volatile' | null {
  const raw = metadata?.refresh_policy
  if (raw === 'static' || raw === 'volatile') return raw
  return null
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

/** Cassandra is infrastructure-only — never list it on the owner connectors page. */
export const OWNER_WIZARD_HIDDEN_SYSTEM_ID = 'cassandra'

export function isOwnerConnectorsHiddenSystem(system: string): boolean {
  return normalizeSystemId(system) === OWNER_WIZARD_HIDDEN_SYSTEM_ID
}

export function isOwnerWizardHiddenSystem(system: string | null | undefined): boolean {
  return isOwnerConnectorsHiddenSystem(system ?? '')
}

export function isOwnerConnectorsHiddenVertical(verticalId: string): boolean {
  return verticalId.trim().toLowerCase() === 'data'
}

/** Drop leftover demo / infra systems that must not appear as wizard cards. */
export function filterOwnerWizardConnectors(
  connectors: readonly OwnerConnectorSystem[] | null | undefined,
): OwnerConnectorSystem[] {
  if (!connectors?.length) return []
  return connectors.filter((connector) => !isOwnerWizardHiddenSystem(connector.system))
}

/** Owner-facing system title — Test vertical uses System A / System B; never "cassandra". */
export function ownerConnectorDisplayName(
  verticalId: string | null | undefined,
  system: string,
  displayName?: string | null,
): string {
  const labeled = catalogSystemDisplayLabel(system, {
    vertical: verticalId,
    systemLabel: displayName,
  })
  if (labeled && labeled.toLowerCase() !== OWNER_WIZARD_HIDDEN_SYSTEM_ID) return labeled
  const trimmed = (displayName ?? '').trim()
  if (trimmed && trimmed.toLowerCase() !== OWNER_WIZARD_HIDDEN_SYSTEM_ID) return trimmed
  return 'System'
}

export const UPLOAD_IDENTIFIER_FIELDS = [
  { id: 'email', label: 'Email' },
  { id: 'phone', label: 'Phone' },
  { id: 'first_name', label: 'First name' },
  { id: 'last_name', label: 'Last name' },
  { id: 'dob', label: 'Date of birth' },
  { id: 'zip', label: 'ZIP' },
] as const

export type UploadIdentifierFieldId = (typeof UPLOAD_IDENTIFIER_FIELDS)[number]['id']

const UPLOAD_HEADER_ALIASES: Record<UploadIdentifierFieldId, readonly string[]> = {
  email: ['email', 'email_address', 'e_mail', 'mail'],
  phone: ['phone', 'phone_number', 'mobile', 'cell'],
  first_name: ['first_name', 'first', 'firstname', 'given_name', 'fname'],
  last_name: ['last_name', 'last', 'lastname', 'surname', 'family_name', 'lname'],
  dob: ['dob', 'date_of_birth', 'birth_date'],
  zip: ['zip', 'zip_code', 'postal', 'postal_code'],
}

export function normalizeUploadHeader(raw: string): string {
  return raw.trim().toLowerCase().replaceAll(' ', '_').replaceAll('-', '_')
}

/** Parse the first CSV row as headers (quoted fields supported). */
export function parseCsvHeaderRow(text: string): string[] {
  const first = parseCsvRecords(text.replace(/^\uFEFF/, ''))[0] ?? []
  return first.map((h) => h.trim()).filter((h) => h.length > 0)
}

export type CsvDocument = {
  headers: string[]
  rows: string[][]
}

/** Parse a CSV into headers + data rows (quoted fields and newlines in quotes). */
export function parseCsvDocument(text: string): CsvDocument {
  const records = parseCsvRecords(text.replace(/^\uFEFF/, ''))
  const headers = (records[0] ?? []).map((cell) => cell.trim())
  const width = headers.length
  const rows = records.slice(1).map((record) => {
    const next = record.slice(0, width)
    while (next.length < width) next.push('')
    return next
  })
  return { headers, rows }
}

export function serializeCsvDocument(doc: CsvDocument): string {
  const lines = [doc.headers, ...doc.rows].map((cells) =>
    cells.map(csvEscapeField).join(','),
  )
  return `${lines.join('\n')}\n`
}

function csvEscapeField(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replaceAll('"', '""')}"`
  }
  return value
}

function parseCsvRecords(text: string): string[][] {
  const records: string[][] = []
  let row: string[] = []
  let current = ''
  let inQuotes = false
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          current += '"'
          i += 1
        } else {
          inQuotes = false
        }
      } else {
        current += ch
      }
      continue
    }
    if (ch === '"') {
      inQuotes = true
      continue
    }
    if (ch === ',') {
      row.push(current)
      current = ''
      continue
    }
    if (ch === '\n') {
      row.push(current)
      records.push(row)
      row = []
      current = ''
      continue
    }
    if (ch === '\r') {
      continue
    }
    current += ch
  }
  if (current.length > 0 || row.length > 0) {
    row.push(current)
    records.push(row)
  }
  return records
}

export function suggestUploadColumnMapping(
  headers: readonly string[],
  targets: readonly UploadIdentifierFieldId[] = UPLOAD_IDENTIFIER_FIELDS.map((f) => f.id),
): Record<string, string> {
  const byNorm = new Map<string, string>()
  for (const header of headers) {
    const key = normalizeUploadHeader(header)
    if (key && !byNorm.has(key)) byNorm.set(key, header)
  }
  const mapping: Record<string, string> = {}
  const used = new Set<string>()
  for (const target of targets) {
    const aliases = UPLOAD_HEADER_ALIASES[target] ?? [target]
    for (const alias of aliases) {
      const source = byNorm.get(alias)
      if (source && !used.has(source)) {
        mapping[target] = source
        used.add(source)
        break
      }
    }
  }
  return mapping
}

export function uploadMappingComplete(
  mapping: Record<string, string>,
  targets: readonly UploadIdentifierFieldId[] = UPLOAD_IDENTIFIER_FIELDS.map((f) => f.id),
): boolean {
  return targets.some((id) => Boolean(mapping[id]?.trim()))
}

export const EMAIL_FORMAT_OPTIONS = [
  { id: 'loose', label: 'Loose — @ and a dot in the domain' },
  { id: 'standard', label: 'Standard — one @ and a dotted domain' },
  { id: 'strict', label: 'Strict — standard plus a 2+ letter TLD' },
] as const

export const PHONE_FORMAT_OPTIONS = [
  { id: 'digits_10_plus', label: '10 or more digits' },
  { id: 'us_10', label: 'US 10-digit (or 1 + 10 digits)' },
  { id: 'e164', label: 'E.164 — leading +, 10–15 digits' },
] as const

export const REJECTED_ROW_CODE_LABELS: Record<string, string> = {
  email_invalid: 'Email format',
  phone_invalid: 'Phone format',
  no_identifier: 'No identifier',
}

export function rejectedRowCodeLabel(code: string): string {
  return REJECTED_ROW_CODE_LABELS[code] ?? 'Invalid value'
}

/** In-app samples matching admin_api tests/fixtures/upload_mapping/. */
export const UPLOAD_SAMPLE_CSV: Record<
  | 'success'
  | 'success_email_only'
  | 'success_phone_only'
  | 'autobind'
  | 'remap'
  | 'failure_no_identifier'
  | 'failure_no_usable_rows'
  | 'corrupted_emails'
  | 'corrupted_phones'
  | 'mixed_good_and_corrupt',
  { filename: string; body: string; label: string }
> = {
  success: {
    filename: 'success.csv',
    label: 'Success (name + email)',
    body: 'first_name,last_name,email\nAda,Lovelace,ada@example.com\n',
  },
  success_email_only: {
    filename: 'success_email_only.csv',
    label: 'Success (email only)',
    body: 'email\nada@example.com\n',
  },
  success_phone_only: {
    filename: 'success_phone_only.csv',
    label: 'Success (phone only)',
    body: 'phone\n2025550100\n',
  },
  autobind: {
    filename: 'autobind.csv',
    label: 'Auto-bind',
    body: 'First Name,Last Name,Email Address\nGrace,Hopper,grace@example.com\n',
  },
  remap: {
    filename: 'remap.csv',
    label: 'Remap',
    body: 'Given,Family,Work Email,Department\nAlan,Turing,alan@example.com,Research\n',
  },
  failure_no_identifier: {
    filename: 'failure_no_identifier.csv',
    label: 'Fail (no identifier columns)',
    body: 'department,notes\nResearch,internal only\n',
  },
  failure_no_usable_rows: {
    filename: 'failure_no_usable_rows.csv',
    label: 'Fail (bad email/phone)',
    body: 'email,phone\nnot-an-email,123\n',
  },
  corrupted_emails: {
    filename: 'corrupted_emails.csv',
    label: 'Corrupt emails',
    body: 'email\nnot-an-email\nuser@\n@nodomain.com\n',
  },
  corrupted_phones: {
    filename: 'corrupted_phones.csv',
    label: 'Corrupt phones',
    body: 'phone\n123\nabc\n555-12\n',
  },
  mixed_good_and_corrupt: {
    filename: 'mixed_good_and_corrupt.csv',
    label: 'Mixed good + corrupt',
    body: 'email,phone,first_name\nada@example.com,2025550100,Ada\nnot-an-email,2025550100,Bad\ngrace@example.com,123,Grace\n',
  },
}

export function uploadSampleFile(kind: keyof typeof UPLOAD_SAMPLE_CSV): File {
  const sample = UPLOAD_SAMPLE_CSV[kind]
  return new File([sample.body], sample.filename, { type: 'text/csv' })
}
