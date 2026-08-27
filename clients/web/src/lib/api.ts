// Empty string (Cloud Run same-origin front door) must fall back to /api — not ??.
export const API_BASE = import.meta.env.VITE_ADMIN_API_URL || '/api'

/** Remint this far before JWT `exp` so Architecture B fetches do not send a dead token. */
export const ADMIN_API_TOKEN_REFRESH_SKEW_MS = 60_000

/** True when the SPA calls admin-api cross-origin (Architecture B). Empty URL stays `/api`. */
export function usesDirectAdminApi(): boolean {
  return API_BASE.startsWith('http://') || API_BASE.startsWith('https://')
}

/**
 * JSON URL. Architecture B uses the baked admin-api origin only when a GIS
 * user token is in memory. One Tap often misses behind admin-web IAP — then
 * same-origin `/api` (nginx + IAP headers) keeps the session off the Retry
 * screen. Server-Sent Events stay on `/api/live/events` either way.
 */
export function adminApiRequestUrl(path: string): string {
  if (usesDirectAdminApi() && !getAdminApiUserToken()) {
    return `/api${path}`
  }
  return `${API_BASE}${path}`
}

/** GIS web client id from VITE_ only — never invent or hardcode a client id. */
const GIS_CLIENT_ID = (
  (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) ||
  (import.meta.env.VITE_GIS_CLIENT_ID as string | undefined) ||
  ''
).trim()

export function googleIdentityServicesClientId(): string {
  return GIS_CLIENT_ID
}

function decodeJwtExpiryMs(token: string): number | null {
  try {
    const payload = token.split('.')[1]
    if (!payload) return null
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/')
    const pad =
      normalized.length % 4 === 0 ? '' : '='.repeat(4 - (normalized.length % 4))
    const json = JSON.parse(globalThis.atob(normalized + pad)) as { exp?: unknown }
    return typeof json.exp === 'number' ? json.exp * 1000 : null
  } catch {
    return null
  }
}

/** In-memory user Google ID token (Architecture B). Not persisted. */
let adminApiUserToken: string | null = null
let adminApiUserTokenExpiresAt: number | null = null
let adminApiUserTokenRefresher: (() => Promise<void>) | null = null
const adminApiUserTokenListeners = new Set<() => void>()

function notifyAdminApiUserTokenListeners(): void {
  for (const listener of adminApiUserTokenListeners) listener()
}

/** Fired after the in-memory GIS token is set or cleared. */
export function subscribeAdminApiUserToken(listener: () => void): () => void {
  adminApiUserTokenListeners.add(listener)
  return () => {
    adminApiUserTokenListeners.delete(listener)
  }
}

export function setAdminApiUserToken(token: string | null): void {
  const trimmed = token?.trim() ?? ''
  if (trimmed.length === 0) {
    adminApiUserToken = null
    adminApiUserTokenExpiresAt = null
    notifyAdminApiUserTokenListeners()
    return
  }
  adminApiUserToken = trimmed
  adminApiUserTokenExpiresAt = decodeJwtExpiryMs(trimmed)
  notifyAdminApiUserTokenListeners()
}

export function getAdminApiUserToken(): string | null {
  return adminApiUserToken
}

/**
 * True when Architecture B should remint. Missing / non-JWT lab tokens are not
 * treated as expired — initial mint is AuthProvider, not every fetch.
 */
export function adminApiUserTokenNeedsRefresh(now = Date.now()): boolean {
  if (!adminApiUserToken || adminApiUserTokenExpiresAt == null) return false
  return now >= adminApiUserTokenExpiresAt - ADMIN_API_TOKEN_REFRESH_SKEW_MS
}

/** GIS remint hook registered by auth.tsx. No-op unless VITE_ADMIN_API_URL is set. */
export function registerAdminApiUserTokenRefresher(
  fn: (() => Promise<void>) | null,
): void {
  adminApiUserTokenRefresher = fn
}

export async function refreshAdminApiUserTokenIfNeeded(): Promise<void> {
  if (!usesDirectAdminApi()) return
  if (!adminApiUserTokenNeedsRefresh()) return
  if (!adminApiUserTokenRefresher) return
  await adminApiUserTokenRefresher()
}

export type UserRole = 'super_admin' | 'admin' | 'legal' | 'data_owner' | 'data_user'

/** sessionStorage key for X-Dev-Simulate-Role (super_admin local/dev only). */
export const SIMULATE_ROLE_STORAGE_KEY = 'habeas-cli.simulate-role'

export const SIMULATE_ROLE_VALUES: UserRole[] = [
  'super_admin',
  'admin',
  'legal',
  'data_owner',
  'data_user',
]

export const PENDING_SETTING_INVITE_USERS = 'invite_data_users'

export type PendingSettingStatus = 'pending' | 'skipped' | 'done'

export type PendingSetting = {
  id: string
  title: string
  status: PendingSettingStatus
}

export type ConnectorReminderSeverity = 'approaching' | 'overdue'

export type ConnectorReminder = {
  code: string
  system: string
  vertical_id: string
  severity: ConnectorReminderSeverity
}

export type AssignedVerticalLabel = {
  vertical_id: string
  display_label: string
}

export type MePayload = {
  email: string
  /** Google IAP given_name when present — safe for welcome copy (KD24). */
  given_name?: string | null
  /** Effective role (after X-Dev-Simulate-Role when allowed). */
  role: UserRole
  /** Allowlist role before simulate override. */
  real_role: UserRole
  /** Assigned KD20 vertical ids. Super_admin receives the full catalog. */
  verticals?: string[]
  /** Catalog display labels for assigned verticals (welcome copy). */
  assigned_vertical_labels?: AssignedVerticalLabel[]
  /** True when an assigned vertical still has incomplete connector wizard (KTD17). */
  needs_connector_setup?: boolean
  /** Soft connector reminders — never block login (KTD13). */
  connector_reminders?: ConnectorReminder[]
  /** First-run / changed-settings walkthrough hooks. */
  pending_settings?: PendingSetting[]
}

export function getStoredSimulateRole(): UserRole | null {
  if (typeof sessionStorage === 'undefined') return null
  const value = sessionStorage.getItem(SIMULATE_ROLE_STORAGE_KEY)
  if (
    value === 'super_admin' ||
    value === 'admin' ||
    value === 'legal' ||
    value === 'data_owner' ||
    value === 'data_user'
  ) {
    return value
  }
  return null
}

export function setStoredSimulateRole(role: UserRole | null) {
  if (typeof sessionStorage === 'undefined') return
  if (role == null) {
    sessionStorage.removeItem(SIMULATE_ROLE_STORAGE_KEY)
  } else {
    sessionStorage.setItem(SIMULATE_ROLE_STORAGE_KEY, role)
  }
}

/**
 * Shared admin-api headers. Same-origin `/api` (empty VITE_ADMIN_API_URL) never
 * attaches Authorization — nginx/Vite mint the invoker token. Direct admin-api
 * attaches `Authorization: Bearer` only when a user ID token is in memory.
 */
export function adminApiAuthHeaders(
  extra?: Record<string, string>,
): Record<string, string> {
  const headers: Record<string, string> = { ...extra }
  const simulateRole = getStoredSimulateRole()
  if (simulateRole) {
    headers['X-Dev-Simulate-Role'] = simulateRole
  }
  if (usesDirectAdminApi()) {
    const token = getAdminApiUserToken()
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }
  }
  return headers
}

/** Fast ops reads — lite pipeline, matching progress, header summary. */
export const OPS_FAST_QUERY_TIMEOUT_MS = 8_000

/** Prod probe: first-paint GETs (`/me`, connectors, snapshot/processes, header) must finish under this. */
export const OPS_PROD_PROBE_MAX_MS = 5_000

/** Prod serving GET /me — QCQA HOLD if slower. */
export const OPS_ME_PROD_MAX_MS = 2_000

/** Opt-in full spine walk — batch expand uses lite + OPS_FAST_QUERY_TIMEOUT_MS. */
export const OPS_EXPAND_DETAIL_TIMEOUT_MS = 45_000

/** Default abort for slow ops reads (full pipeline, worker trends, …). */
export const OPS_QUERY_TIMEOUT_MS = 30_000

export type AdminApiFetchInit = RequestInit & {
  /** When set, abort the request after this many milliseconds. */
  timeoutMs?: number
}

function mergeAbortSignals(
  left: AbortSignal | null | undefined,
  right: AbortSignal | null | undefined,
): AbortSignal | undefined {
  if (left == null) return right ?? undefined
  if (right == null) return left
  if (typeof AbortSignal !== 'undefined' && 'any' in AbortSignal) {
    return AbortSignal.any([left, right])
  }
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (left.aborted || right.aborted) {
    controller.abort()
    return controller.signal
  }
  left.addEventListener('abort', abort)
  right.addEventListener('abort', abort)
  return controller.signal
}

/** Optional per-request timeout merged with any caller-provided signal. */
export function adminApiAbortSignal(
  timeoutMs?: number,
  signal?: AbortSignal | null,
): AbortSignal | undefined {
  if (timeoutMs == null || timeoutMs <= 0) return signal ?? undefined
  if (typeof AbortSignal === 'undefined' || !('timeout' in AbortSignal)) {
    return signal ?? undefined
  }
  return mergeAbortSignals(signal, AbortSignal.timeout(timeoutMs))
}

export const DPRA_TIMING_PREFIX = 'dpra-timing'

export type DpraTimingEntry = {
  prefix: 'dpra-timing'
  kind: 'fetch' | 'query'
  route: string
  queryKey?: string
  url?: string
  start: string
  ttfb_ms?: number
  duration_ms: number
  status: number
  abort: boolean
}

function dpraNowMs(): number {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now()
}

function dpraTimingRoute(): string {
  const loc = (globalThis as { location?: { pathname?: unknown } }).location
  return typeof loc?.pathname === 'string' ? loc.pathname : ''
}

function pathSegmentContainsAt(segment: string): boolean {
  if (!segment) return false
  let decoded = segment
  try {
    decoded = decodeURIComponent(segment)
  } catch {
    decoded = segment
  }
  return decoded.includes('@') || /%40/i.test(segment)
}

/** Path + query keys only. Drops query values. Redacts path segments that contain `@`. */
export function sanitizeDpraTimingUrl(path: string): string {
  let pathname = path
  let search = ''
  if (/^https?:\/\//i.test(path)) {
    try {
      const parsed = new URL(path)
      pathname = parsed.pathname
      search = parsed.search.startsWith('?') ? parsed.search.slice(1) : ''
    } catch {
      const q = path.indexOf('?')
      pathname = q >= 0 ? path.slice(0, q) : path
      search = q >= 0 ? path.slice(q + 1) : ''
    }
  } else {
    const hash = path.indexOf('#')
    const withoutHash = hash >= 0 ? path.slice(0, hash) : path
    const q = withoutHash.indexOf('?')
    pathname = q >= 0 ? withoutHash.slice(0, q) : withoutHash
    search = q >= 0 ? withoutHash.slice(q + 1) : ''
  }

  const redactedPath = pathname
    .split('/')
    .map((segment) => (pathSegmentContainsAt(segment) ? '[redacted]' : segment))
    .join('/')

  if (!search) return redactedPath
  const keys: string[] = []
  for (const part of search.split('&')) {
    if (!part) continue
    const key = part.split('=', 1)[0]
    if (key) keys.push(key)
  }
  return keys.length > 0 ? `${redactedPath}?${keys.join('&')}` : redactedPath
}

function isDpraTimingAbort(error: unknown): boolean {
  if (error == null || typeof error !== 'object') return false
  const name = 'name' in error ? String(error.name) : ''
  return name === 'AbortError' || name === 'TimeoutError'
}

/** Structured timing line. Never pass bodies, headers, Authorization, emails, or vendor ids. */
export function logDpraTiming(entry: Omit<DpraTimingEntry, 'prefix'> & { prefix?: 'dpra-timing' }): void {
  const line: DpraTimingEntry = {
    prefix: DPRA_TIMING_PREFIX,
    kind: entry.kind,
    route: entry.route,
    start: entry.start,
    duration_ms: entry.duration_ms,
    status: entry.status,
    abort: entry.abort,
  }
  if (entry.queryKey != null) line.queryKey = entry.queryKey
  if (entry.url != null) line.url = entry.url
  if (entry.ttfb_ms != null) line.ttfb_ms = entry.ttfb_ms
  console.info(line)
}

export async function fetchAdminApi<T>(path: string, init?: AdminApiFetchInit): Promise<T> {
  await refreshAdminApiUserTokenIfNeeded()
  const { timeoutMs, signal: callerSignal, ...rest } = init ?? {}
  const headers = adminApiAuthHeaders({
    Accept: 'application/json',
    'Content-Type': 'application/json',
  })

  const start = new Date().toISOString()
  const startedAt = dpraNowMs()
  let ttfbMs: number | undefined
  let status = 0
  let abort = false

  try {
    let response: Response
    try {
      response = await fetch(adminApiRequestUrl(path), {
        ...rest,
        signal: adminApiAbortSignal(timeoutMs, callerSignal),
        headers: {
          ...headers,
          ...rest.headers,
        },
      })
    } finally {
      ttfbMs = Math.round(dpraNowMs() - startedAt)
    }
    status = response.status

    if (!response.ok) {
      const detail = await response.text()
      throw new Error(`Admin API ${response.status}: ${detail || response.statusText}`)
    }

    // 204 No Content (e.g. DELETE assignment) — no JSON body.
    if (response.status === 204) {
      return undefined as T
    }
    const text = await response.text()
    if (!text) {
      return undefined as T
    }
    return JSON.parse(text) as T
  } catch (error) {
    abort = isDpraTimingAbort(error)
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new Error(
        `Admin API timed out after ${timeoutMs ?? OPS_QUERY_TIMEOUT_MS}ms: ${path}`,
      )
    }
    throw error
  } finally {
    logDpraTiming({
      kind: 'fetch',
      route: dpraTimingRoute(),
      url: sanitizeDpraTimingUrl(path),
      start,
      ttfb_ms: ttfbMs,
      duration_ms: Math.round(dpraNowMs() - startedAt),
      status,
      abort,
    })
  }
}

export type HealthPayload = {
  status: string
  service?: string
}

export type IntakeSource = 'webform' | 'drop' | 'csv' | 'manual'

export type RequesterContact = {
  name?: string | null
  email?: string | null
  phone?: string | null
}

export type RequestRecord = {
  id: string
  received_at: string
  intake_source: IntakeSource
  raw_record_id: number | null
  /** 2-letter USPS acronym — not PII */
  requestor_state?: string | null
  request_type?: string
  /** Non-DROP display label when available — not logged server-side */
  display_label?: string | null
  /** Non-DROP contact for legal/admin — authorized display only */
  contact?: RequesterContact | null
  /** True when DROP row is still open on the spine */
  drop_open?: boolean | null
}

export type ManualRequestInput = {
  request_type?: string
  first_name?: string
  last_name?: string
  email?: string
  phone?: string
  zip?: string
  dob?: string
  state: string
  external_id?: string
}

export async function getMe() {
  const me = await fetchAdminApi<MePayload>('/me', {
    timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS,
  })
  return {
    ...me,
    real_role: me.real_role ?? me.role,
  }
}

export type MeHomePayload = {
  given_name: string
  pending_attention_count: number
  urgent_deadline_days: number | null
  stage_counts_year: { ingest: number; matching: number; fulfillment: number; notice: number }
  next_ca_drop: { next_run_at: string | null; cadence: string | null; schedule_utc?: string | null }
  next_data_refresh: { system: string; label: string; next_at: string | null } | null
  comments: Array<{ request_id: string; actor: string; occurred_at: string; body: string }>
  notifications: Array<{
    id: string
    kind: 'comment' | 'batch'
    title: string
    occurred_at: string
    request_id?: string
  }>
}

export function getMeHome(): Promise<MeHomePayload> {
  return fetchAdminApi<MeHomePayload>('/me/home', {
    timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS,
  })
}

export function patchPendingSetting(body: { id: string; status: 'skipped' | 'done' }) {
  return fetchAdminApi<MePayload>('/me/pending-settings', {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function getHealth() {
  // Prefer /readyz: Cloud Run's public edge returns a Google HTML 404 for /healthz.
  return fetchAdminApi<HealthPayload>('/readyz')
}

export function getRequest(requestId: string) {
  return fetchAdminApi<RequestRecord>(`/requests/${encodeURIComponent(requestId)}`)
}

export type IdentityVerificationRecord = {
  id: number
  request_id: string
  status: string
  method: string | null
  verified_by: string
  notes: string | null
  verified_at: string
}

export function getLatestIdentityVerification(requestId: string) {
  return fetchAdminApi<IdentityVerificationRecord | null>(
    `/requests/${encodeURIComponent(requestId)}/identity-verification/latest`,
  )
}

export function postIdentityVerification(
  requestId: string,
  body: {
    status?: 'verified' | 'failed' | 'pending'
    method?: string
    notes?: string
  },
) {
  return fetchAdminApi<IdentityVerificationRecord>(
    `/requests/${encodeURIComponent(requestId)}/identity-verification`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  )
}

export type RequestListPage = {
  items: RequestRecord[]
  total: number
  limit: number
  offset: number
}

export function listRequests(options?: {
  intakeSource?: IntakeSource
  sourceBucket?: 'drop' | 'other'
  stage?: string
  posture?: 'in_queue' | 'in_progress' | 'complete'
  requestType?: string
  requestorState?: string
  receivedAfter?: string
  receivedBefore?: string
  limit?: number
  offset?: number
  q?: string
  timeoutMs?: number
}) {
  const search = new URLSearchParams()
  if (options?.intakeSource) search.set('intake_source', options.intakeSource)
  if (options?.sourceBucket) search.set('source_bucket', options.sourceBucket)
  if (options?.stage) search.set('stage', options.stage)
  if (options?.posture) search.set('posture', options.posture)
  if (options?.requestType) search.set('request_type', options.requestType)
  if (options?.requestorState) search.set('requestor_state', options.requestorState)
  if (options?.receivedAfter) search.set('received_after', options.receivedAfter)
  if (options?.receivedBefore) search.set('received_before', options.receivedBefore)
  if (options?.limit != null) search.set('limit', String(options.limit))
  if (options?.offset != null) search.set('offset', String(options.offset))
  if (options?.q?.trim()) search.set('q', options.q.trim())
  const query = search.toString()
  return fetchAdminApi<RequestListPage>(`/requests${query ? `?${query}` : ''}`, {
    timeoutMs: options?.timeoutMs,
  })
}

export function createManualRequest(body: ManualRequestInput) {
  return fetchAdminApi<RequestRecord>('/requests', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export type AgentBatchUploadResult = {
  batch_id: string
  source_filename: string | null
  input_row_count: number
  cleaned_row_count: number
  inserted_count: number
  skipped_row_count: number
  email_split_count: number
  request_ids: string[]
}

export async function postAgentBatchUpload(file: File) {
  await refreshAdminApiUserTokenIfNeeded()
  const headers = adminApiAuthHeaders({ Accept: 'application/json' })
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(adminApiRequestUrl('/requests/agent-batch'), {
    method: 'POST',
    headers,
    body: form,
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`Admin API ${response.status}: ${detail || response.statusText}`)
  }
  return (await response.json()) as AgentBatchUploadResult
}

export type ApprovalRecord = {
  id: number
  request_id: string
  action_type: string
  status: string
  approver_role?: string | null
  decided_by?: string | null
  decision_reason?: string | null
}

export type ApprovalDecisionInput = {
  decided_by: string
  decision_reason?: string
}

export function listMatchingReviewApprovals(status: string = 'pending') {
  const params = new URLSearchParams({
    action_type: 'matching.review',
    status,
  })
  return fetchAdminApi<ApprovalRecord[]>(`/approvals?${params}`)
}

export function approveMatchingReview(approvalId: number, body: ApprovalDecisionInput) {
  return fetchAdminApi<ApprovalRecord>(`/approvals/${approvalId}/approve`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export type StepStatusCount = {
  step: string
  status: string
  count: number
}

export type RawListTypeCount = {
  list_type: string
  total: number
  response_status_null: number
  response_status_set: number
}

export type DropRequestThin = {
  id: string
  received_at: string | null
  raw_record_id: number | null
}

export type MatchTypeFilter = 'single_match' | 'multi_match' | 'not_found'

export type MatchingResultSummary = {
  request_id: string
  matched: boolean
  match_count: number
  match_type?: MatchTypeFilter
  matched_via: string
  recorded_at: string | null
  /** 2-letter USPS acronym only — not PII */
  requestor_state?: string | null
}

export type WorkflowAssignmentTarget = 'reviewer' | 'legal' | 'data_owner'

export type WorkflowAssignmentSummary = {
  target_role: WorkflowAssignmentTarget | string
  kind?: string | null
  assignee_identity?: string | null
  id?: number
  status?: string
}

export type MatchingAttemptRow = {
  id: number
  attempt_number: number
  status: string
  attempted_at: string | null
  completed_at: string | null
  error_code: string | null
  /** Present when the attempt failed; redacted server-side. */
  error_message?: string | null
  audit_payload: Record<string, unknown>
}

export type MatchingResultRow = MatchingResultSummary & {
  match_type: MatchTypeFilter
  /** Computed at read time from match_count (0→5, 1→3, N→4). */
  recommended_response_status?: number | null
  review_status: string
  approval_id: number | null
  assignment?: WorkflowAssignmentSummary | null
}

export type MatchingResultsStats = {
  total: number
  single_match: number
  multi_match: number
  not_found: number
  review_pending: number
  review_approved: number
  review_none: number
}

export type MatchingResultsFilters = {
  match_type: MatchTypeFilter | null
  q: string | null
  request_id: string | null
  state: string | null
  recorded_after: string | null
  recorded_before: string | null
  /** Stats are global unfiltered totals; list filters only narrow results */
  stats_scope: 'global' | string
}

export type MatchingResultsPayload = {
  stats: MatchingResultsStats
  results: MatchingResultRow[]
  limit: number
  match_type_filter: MatchTypeFilter | null
  filters?: MatchingResultsFilters
}

export type MatchedPersonPhone = {
  type: 'cell' | 'land' | string
  number: string
}

export type MatchedPersonContact = {
  dwid: string
  state: string
  first_initial: string | null
  last_initial: string | null
  /** Optional full last name when enrichment returns it (falls back to initials). */
  last_name?: string | null
  dob: string | null
  email: string | null
  phones: MatchedPersonPhone[]
}

export type MatchedHash = {
  kind: string
  hash: string
  matched_via?: string
}

export type MatchedContactsError = {
  message?: string | null
  code?: string | null
  stage?: string | null
  hint?: string | null
  exc_type?: string | null
}

export type MatchedChannel = 'email' | 'phone' | 'ndz'

export type MatchingResultDetail = MatchingResultRow & {
  attempt_id: number | null
  decided_by: string | null
  decided_at: string | null
  decision_reason: string | null
  attempts?: MatchingAttemptRow[]
  assignment?: WorkflowAssignmentSummary | null
  matched_contacts?: MatchedPersonContact[]
  matched_contacts_status?: 'ok' | 'none' | 'unavailable' | 'not_live' | string
  matched_contacts_error?: MatchedContactsError | null
  /** CA DROP lookup hashes — not emails/phones. Authorized reviewers only. */
  matched_hashes?: MatchedHash[]
  /** Non-hash match channels from matched_via / attempt list_type. */
  matched_channels?: MatchedChannel[]
  /** Owner vertical-item review — not request-level assignment. */
  vertical?: string | null
  vertical_label?: string | null
  system?: string | null
  system_label?: string | null
  color_token?: string | null
  /** `request` = legacy omitted-system Data URL; `system` = this inbox item. */
  match_scope?: 'request' | 'system'
  /** CA DROP keeps people/hashes; sheet/SaaS systems are catalog stubs. */
  result_kind?: 'ca_drop' | 'sheet_stub' | 'saas_stub'
  not_live_reason?: string | null
  selected_dwids?: string[] | null
  disposition_status?: number | null
}

export type BulkApproveMatchingResultsInput = {
  match_type: MatchTypeFilter
  vertical: string
  system: string
  decided_by?: string
  decision_reason?: string
}

export type BulkApproveMatchingResultsResult = {
  status: string
  match_type: MatchTypeFilter
  vertical?: string
  system?: string
  ensured_count?: number
  approved_count: number
  decided_count?: number
  pending_count?: number
  approval_ids: number[]
  request_ids: string[]
}

export type HashIndexRefreshStatus = {
  pending: number
  attempts_by_status: { status: string; count: number }[]
  last_run: {
    state: string
    status: string
    finished_at: string | null
    rows_email: number | null
    rows_phone: number | null
    rows_ndz: number | null
    error_message: string | null
    rematch_enqueued_count: number
  } | null
}

export type CaDropSchedule = {
  label: string
  schedule_utc: string
  cadence: string
  next_run_at: string
  last_success_at: string | null
  interval_days?: number | null
  month_days?: number[] | null
}

export type WorkerScheduleKind = 'interval_days' | 'interval_minutes' | 'month_days'

export type WorkerSchedule = {
  job_key: string
  job_name: string
  label: string
  enabled: boolean
  schedule_kind: WorkerScheduleKind
  interval_days: number | null
  interval_minutes: number | null
  month_days: number[] | null
  time_utc: string | null
  cron: string
  timezone: string
  next_run_at: string | null
  last_success_at: string | null
  scheduler_state: string
  scheduler_reachable: boolean
}

export type WorkerSchedulesPayload = {
  schedules: WorkerSchedule[]
}

export type WorkerSchedulePatch = {
  job_key: string
  enabled?: boolean
  interval_minutes?: number
  interval_days?: number
  month_days?: number[]
  time_utc?: string
}

export type HashIndexRunMetrics = {
  run_status: string | null
  run_started_at: string | null
  run_finished_at: string | null
  rows_email: number | null
  rows_phone: number | null
  rows_ndz: number | null
  rematch_enqueued_count: number | null
  run_error_message: string | null
}

export type WorkerHealthProbe = {
  name: string
  ok: boolean
  status_code?: number | null
  ready?: { status?: string; service?: string }
  error?: string
}

export type ResponseStatusCount = {
  response_status: number | null
  count: number
}

export type DropFulfillmentStatus = {
  ready: number
  response_status_null: number
  by_response_status: ResponseStatusCount[]
}

export type DropPipelineStatus = {
  connector_attempts: StepStatusCount[]
  ingest_attempts: StepStatusCount[]
  raw_requests_by_list_type: RawListTypeCount[]
  /** Absent on older admin-api revisions that predate fulfillment stage stats. */
  fulfillment?: DropFulfillmentStatus
  /** Absent on older admin-api revisions. */
  approaching_sla?: {
    connector: number
    ingest: number
    matching: number
    matching_review: number
    thresholds_hours: {
      connector: number
      ingest: number
      matching: number
      matching_review: number
    }
  }
  drop_requests: {
    count: number
    recent: DropRequestThin[]
  }
  matching_attempts: {
    pending: number
    success: number
    by_status: { status: string; count: number }[]
    /** Absent on older admin-api revisions that predate chunk drain. */
    drain?: {
      active: boolean
      holder: string | null
      expires_at: string | null
    }
  }
  matching_results_recent: MatchingResultSummary[]
  matching_review: {
    action_type: string
    pending: number
    approved: number
    by_status: { status: string; count: number }[]
  }
  /** Absent on older admin-api revisions that predate hash-index ops. */
  hash_index_refresh?: HashIndexRefreshStatus
  /** Absent on older admin-api revisions. */
  ca_drop_schedule?: CaDropSchedule
  worker_health: Record<string, WorkerHealthProbe>
}

export type DropWorkerQueue = {
  table: string | null
  pending: number
  claimed: number
  in_flight: number
  failed_terminal: number
  oldest_pending_age_seconds: number | null
}

export type DropWorkerRecord = {
  name: string
  ok: boolean
  status_code: number | null
  ready: { status?: string; service?: string }
  queue: DropWorkerQueue
  pool: {
    configured_concurrency: number | null
    max_attempts?: number | null
    note?: string
  }
}

export type DropWorkersPayload = {
  workers: DropWorkerRecord[]
}

export type HealthQueueRecord = {
  worker: string
  table: string | null
  by_status: { status: string; count: number }[]
  pending: number
  claimed: number
  in_flight: number
  failed_terminal: number
  oldest_pending_age_seconds: number | null
  pool: {
    configured_concurrency: number | null
    max_attempts?: number | null
    note?: string
  }
}

export type HealthQueuesPayload = {
  queues: HealthQueueRecord[]
}

export type DropGlobalStats = {
  open_drop_requests: number
  matching_review_pending: number
  matching_failed_terminal: number
  hash_index_refresh_inflight: number
  workers_down: number
  workers_total: number
}

/** Cheap header counters — no raw-spine scan (GET /ops/drop/pipeline/summary). */
export type DropPipelineSummary = {
  drop_requests: { count: number }
  matching_review: { pending: number }
  workers_down?: number | null
  workers_total?: number
  workers_stale?: boolean
  worker_health: Record<string, WorkerHealthProbe>
  ca_drop_schedule?: CaDropSchedule
}

/** Live matching counters — GET /ops/drop/matching-progress. */
export type DropMatchingProgress = {
  pending: number
  claimed: number
  success: number
  by_status: { status: string; count: number }[]
  drain: {
    active: boolean
    holder: string | null
    expires_at: string | null
  }
}

/** Unified paint payload — GET /ops/drop/console/snapshot. */
export type DropConsoleSummary = {
  as_of?: string
  open_requests: number
  review_pending: number
  workers_down: number
  workers_total: number
  workers_stale: boolean
  worker_health: Record<string, WorkerHealthProbe>
  ca_drop_schedule?: CaDropSchedule
  drop_requests: { count: number }
  matching_review: { action_type: string; pending: number }
}

export type DropConsoleSnapshot = {
  as_of: string
  summary: DropConsoleSummary
  matching_progress: DropMatchingProgress
  processes: BulkProcessesPayload
  recent_processes: {
    days: number
    processes: BulkProcessSummary[]
  }
}

export function getDropConsoleSnapshot(params?: {
  process_days?: number
  process_limit?: number
  recent_days?: number
  recent_limit?: number
}) {
  const search = new URLSearchParams()
  if (params?.process_days != null) {
    search.set('process_days', String(params.process_days))
  }
  if (params?.process_limit != null) {
    search.set('process_limit', String(params.process_limit))
  }
  if (params?.recent_days != null) {
    search.set('recent_days', String(params.recent_days))
  }
  if (params?.recent_limit != null) {
    search.set('recent_limit', String(params.recent_limit))
  }
  const query = search.toString()
  return fetchAdminApi<DropConsoleSnapshot>(
    `/ops/drop/console/snapshot${query ? `?${query}` : ''}`,
    { timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS },
  )
}

export function getDropPipeline() {
  return fetchAdminApi<DropPipelineStatus>('/ops/drop/pipeline', {
    timeoutMs: OPS_QUERY_TIMEOUT_MS,
  })
}

export function getDropPipelineLite() {
  return fetchAdminApi<DropPipelineStatus>('/ops/drop/pipeline?detail=lite', {
    timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS,
  })
}

export function getDropPipelineSummary() {
  return fetchAdminApi<DropPipelineSummary>('/ops/drop/pipeline/summary', {
    timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS,
  })
}

export function getDropMatchingProgress() {
  return fetchAdminApi<DropMatchingProgress>('/ops/drop/matching-progress', {
    timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS,
  })
}

export type BulkProcessSummary = {
  process_id: number
  intake_source: string
  process_at: string | null
  completed_at: string | null
  download_status: string
  label: string
  linkable: boolean
  overall?: {
    percent: number
    current_stage: string
    status: string
  }
  request_rows?: number
  raw_rows?: number
  /** Lite ledger stages (download/land/promote) — collapsed paint without expand. */
  stages?: {
    download?: BulkProcessStageCounts
    land?: BulkProcessStageCounts
    promote?: BulkProcessStageCounts
  }
  /** Counts-only per-vertical posture — present once the batch rollup fills it. */
  verticals?: BulkProcessVerticalStats[]
}

export type CollapsedPipelineCardFields = {
  title: string
  status: string
  percent: number | null
  requestRows: number | null
  currentStage: string | null
}

/** Date / status / counts for a collapsed bulk row from lite list or snapshot fields. */
export function collapsedPipelineCardFields(
  row: BulkProcessSummary,
): CollapsedPipelineCardFields {
  let title = row.label?.trim() || '—'
  if (row.process_at) {
    const start = new Date(row.process_at)
    if (!Number.isNaN(start.getTime())) {
      title = start.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    }
  }
  const status = row.overall?.status || row.download_status || '—'
  const percent =
    typeof row.overall?.percent === 'number' ? row.overall.percent : null
  const requestRows =
    typeof row.request_rows === 'number' ? row.request_rows : null
  const currentStage = row.overall?.current_stage ?? null
  return { title, status, percent, requestRows, currentStage }
}

export type CollapsedBulkRowDisplay = {
  dateLabel: string
  sourceLabel: string
  statusLabel: string
  progressLabel: string
  countLabel: string | null
}

function formatCollapsedBulkProcessAt(processAt: string | null | undefined): string | null {
  if (!processAt) return null
  const start = new Date(processAt)
  if (Number.isNaN(start.getTime())) return null
  return start.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

/** Collapsed pipeline batch chips — never blank a field the API returned. */
export function collapsedBulkRowDisplay(
  row: Pick<
    BulkProcessSummary,
    | 'process_at'
    | 'intake_source'
    | 'label'
    | 'download_status'
    | 'overall'
    | 'request_rows'
  >,
): CollapsedBulkRowDisplay {
  const fromAt = formatCollapsedBulkProcessAt(row.process_at)
  const label = row.label?.trim() ?? ''
  const intake = (row.intake_source ?? '').trim()
  const sourceLabel = intake === 'drop' ? 'CA DROP' : intake
  const dateLabel = fromAt
    ? sourceLabel
      ? `${fromAt} · ${sourceLabel}`
      : fromAt
    : label || sourceLabel || '—'
  const statusKey = (row.overall?.status || row.download_status || '').trim()
  const statusLabel = statusKey.replaceAll('_', ' ')
  const percent = row.overall?.percent
  const progressLabel =
    percent != null && Number.isFinite(percent) ? `${percent}%` : ''
  const countLabel = row.request_rows != null ? `${row.request_rows} req` : null
  return { dateLabel, sourceLabel, statusLabel, progressLabel, countLabel }
}

export type BulkProcessStageCounts = {
  total: number
  open: number
  success: number
  failed: number
  other?: number
  by_list_type?: { list_type: string | null; status: string; count: number }[]
}

/** Stage counters at (download_id, vertical, stage) grain — counts only, never PII. */
export type BulkProcessVerticalStageCounts = {
  total: number
  open: number
  success: number
  failed: number
  in_flight: number
}

/** One vertical's posture on a bulk batch; stage counters optional until live. */
export type BulkProcessVerticalStats = {
  vertical: string
  label: string
  live: boolean
  catalog_only: boolean
  matching?: BulkProcessVerticalStageCounts
  review?: BulkProcessVerticalStageCounts
  fulfillment?: BulkProcessVerticalStageCounts
}

export type BulkProcessDetail = {
  process_id: number
  intake_source: string
  process_at: string | null
  completed_at: string | null
  label: string
  download_status: string
  raw_rows: number
  request_rows: number
  /** lite = ledger only (expand default). full = raw-spine walk. */
  detail?: 'lite' | 'full'
  stages: {
    download: BulkProcessStageCounts
    land: BulkProcessStageCounts
    promote: BulkProcessStageCounts
    matching: BulkProcessStageCounts
    review: BulkProcessStageCounts
    fulfillment: BulkProcessStageCounts
  }
  overall: {
    percent: number
    current_stage: string
    status: string
  }
  /** Counts-only per-vertical × stage rollup (drop_bulk_vertical_stats). */
  verticals?: BulkProcessVerticalStats[]
}

export type BulkProcessesPayload = {
  day: string
  days?: number
  processes: BulkProcessSummary[]
}

export type BulkProcessRun = {
  run_id: string
  job: string
  attempt_id: number
  step: string
  status: string
  started_at: string | null
  completed_at: string | null
  attempt_number: number
  request_id: string | null
}

export type BulkProcessRunGroup = {
  process_id: number
  intake_source: string
  process_at: string | null
  label: string
  download_status: string
  run_count: number
  runs: BulkProcessRun[]
}

export type BulkProcessRunsPayload = {
  stages: string[]
  groups: BulkProcessRunGroup[]
}

export type WorkerTrendWindowStats = {
  total: number
  failed: number
  error_rate: number
  avg_attempts: number
}

export type WorkerTrendRow = {
  worker: string
  current: WorkerTrendWindowStats
  previous: WorkerTrendWindowStats
  delta: { error_rate: number; avg_attempts: number; total: number }
  anomalies: string[]
  signal: 'ok' | 'watch' | string
}

export type WorkerTrendsPayload = {
  window: string
  window_hours: number
  current_start: string
  previous_start: string
  as_of: string
  workers: WorkerTrendRow[]
}

export function listDropBulkProcesses(params?: {
  day?: string
  days?: number
  intake_source?: string
  download_status?: string
  overall_status?: string
  include_summary?: boolean
  limit?: number
}) {
  const search = new URLSearchParams()
  if (params?.day) search.set('day', params.day)
  if (params?.days != null) search.set('days', String(params.days))
  if (params?.intake_source) search.set('intake_source', params.intake_source)
  if (params?.download_status) search.set('download_status', params.download_status)
  if (params?.overall_status) search.set('overall_status', params.overall_status)
  if (params?.include_summary) search.set('include_summary', 'true')
  if (params?.limit != null) search.set('limit', String(params.limit))
  const query = search.toString()
  return fetchAdminApi<BulkProcessesPayload>(
    `/ops/drop/processes${query ? `?${query}` : ''}`,
    { timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS },
  )
}

export function getDropBulkProcess(
  processId: number,
  opts?: { detail?: 'lite' | 'full' },
) {
  const detail = opts?.detail ?? 'lite'
  const timeoutMs =
    detail === 'full' ? OPS_EXPAND_DETAIL_TIMEOUT_MS : OPS_FAST_QUERY_TIMEOUT_MS
  return fetchAdminApi<BulkProcessDetail>(
    `/ops/drop/processes/${processId}?detail=${encodeURIComponent(detail)}`,
    { timeoutMs },
  )
}

export function listDropBulkProcessRuns(params: {
  stage: string
  day?: string
  days?: number
  process_id?: number
  status?: string
  detail?: 'lite' | 'full'
}) {
  const search = new URLSearchParams()
  search.set('stage', params.stage)
  search.set('detail', params.detail ?? 'lite')
  if (params.day) search.set('day', params.day)
  if (params.days != null) search.set('days', String(params.days))
  if (params.process_id != null) search.set('process_id', String(params.process_id))
  if (params.status) search.set('status', params.status)
  const timeoutMs =
    (params.detail ?? 'lite') === 'full'
      ? OPS_EXPAND_DETAIL_TIMEOUT_MS
      : OPS_FAST_QUERY_TIMEOUT_MS
  return fetchAdminApi<BulkProcessRunsPayload>(
    `/ops/drop/processes/runs?${search.toString()}`,
    { timeoutMs },
  )
}

export function getDropWorkerTrends(window: '8h' | '1w' | '3m' = '1w') {
  return fetchAdminApi<WorkerTrendsPayload>(
    `/ops/drop/workers/trends?window=${encodeURIComponent(window)}`,
  )
}

export function getDropWorkers() {
  return fetchAdminApi<DropWorkersPayload>('/ops/drop/workers')
}

export function getHealthQueues() {
  return fetchAdminApi<HealthQueuesPayload>('/ops/health/queues')
}

export function getDropGlobalStats() {
  return fetchAdminApi<DropGlobalStats>('/ops/drop/stats/global')
}

export type RetryConfigTable = {
  table_name: string
  max_attempts: number
  default_max_attempts: number
  overridden: boolean
  updated_at: string | null
  updated_by: string | null
  apply_note: string
  /** Additive when discovery expands retry-config. */
  worker_key?: string | null
  supports_attempt_retry?: boolean
}

export type RetryConfigPayload = {
  tables: RetryConfigTable[]
  floor: number
}

export function getRetryConfig() {
  return fetchAdminApi<RetryConfigPayload>('/ops/health/retry-config')
}

export function patchRetryConfig(body: { table_name: string; max_attempts: number }) {
  return fetchAdminApi<{ status: string; table_name: string; max_attempts: number }>(
    '/ops/health/retry-config',
    {
      method: 'PATCH',
      body: JSON.stringify(body),
    },
  )
}

export function getWorkerSchedules() {
  return fetchAdminApi<WorkerSchedulesPayload>('/ops/workers/schedules')
}

export function patchWorkerSchedule(body: WorkerSchedulePatch) {
  return fetchAdminApi<{ status: string; schedule: WorkerSchedule; mode: string }>(
    '/ops/workers/schedules',
    {
      method: 'PATCH',
      body: JSON.stringify(body),
    },
  )
}

export function postDropDownload() {
  return fetchAdminApi<Record<string, unknown>>('/ops/drop/download', { method: 'POST' })
}

export function postDropLand(body?: { land_attempt_id?: number }) {
  return fetchAdminApi<Record<string, unknown>>('/ops/drop/land', {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
  })
}

export function postDropPromote(body?: { promote_attempt_id?: number }) {
  return fetchAdminApi<Record<string, unknown>>('/ops/drop/promote', {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
  })
}

export function postDropDispatch() {
  return fetchAdminApi<Record<string, unknown>>('/ops/drop/dispatch', { method: 'POST' })
}

export function postDropMatch() {
  return fetchAdminApi<Record<string, unknown>>('/ops/drop/match', { method: 'POST' })
}

export function postDropFulfill(body?: { request_id?: string }) {
  return fetchAdminApi<Record<string, unknown>>('/ops/drop/fulfill', {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
  })
}

/** Access / suppression artifact for operator handoff (admin-api fulfillment ops). */
export type FulfillmentArtifact = {
  request_id: string
  kind: 'access' | 'suppression' | null
  fulfillment_artifact_uri: string | null
  shareable_url: string | null
  access_delivery_status: string | null
  attempt_status: string | null
}

export function getFulfillmentArtifact(requestId: string) {
  return fetchAdminApi<FulfillmentArtifact>(
    `/ops/fulfillment/requests/${encodeURIComponent(requestId)}/artifact`,
  )
}

export function patchAccessDeliveryStatus(
  requestId: string,
  body: { status: 'pending' | 'delivered' | 'failed' | 'recalled'; notes?: string },
) {
  return fetchAdminApi<FulfillmentArtifact>(
    `/ops/fulfillment/requests/${encodeURIComponent(requestId)}/delivery-status`,
    {
      method: 'PATCH',
      body: JSON.stringify(body),
    },
  )
}

export function postHashIndexRefreshEnqueueAll(body?: { list_types?: string[] }) {
  return fetchAdminApi<Record<string, unknown>>('/ops/drop/hash-index-refresh/enqueue-all', {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
  })
}

export function postHashIndexRefreshEnqueue(body?: { state?: string; list_types?: string[] }) {
  return fetchAdminApi<Record<string, unknown>>('/ops/drop/hash-index-refresh/enqueue', {
    method: 'POST',
    body: JSON.stringify(body ?? { state: 'CA' }),
  })
}

export function postHashIndexRefreshProcess() {
  return fetchAdminApi<Record<string, unknown>>('/ops/drop/hash-index-refresh/process', {
    method: 'POST',
  })
}

export function getDropMatchingResults(params?: {
  match_type?: MatchTypeFilter
  q?: string
  request_id?: string
  state?: string
  recorded_after?: string
  recorded_before?: string
  limit?: number
}) {
  const search = new URLSearchParams()
  if (params?.match_type) search.set('match_type', params.match_type)
  if (params?.q) search.set('q', params.q)
  if (params?.request_id) search.set('request_id', params.request_id)
  if (params?.state) search.set('state', params.state)
  if (params?.recorded_after) search.set('recorded_after', params.recorded_after)
  if (params?.recorded_before) search.set('recorded_before', params.recorded_before)
  if (params?.limit != null) search.set('limit', String(params.limit))
  const query = search.toString()
  return fetchAdminApi<MatchingResultsPayload>(
    `/ops/drop/matching-results${query ? `?${query}` : ''}`,
  )
}

export function getDropMatchingResultDetail(requestId: string) {
  return fetchAdminApi<MatchingResultDetail>(`/ops/drop/matching-results/${requestId}`)
}

/** MDR person search — same BQ person/phones shape as matching-result contacts. */
export type MdrPeopleSearchPayload = {
  contacts: MatchedPersonContact[]
}

export function searchMdrPeople(q: string, opts: { state: string; limit?: number }) {
  const search = new URLSearchParams()
  search.set('q', q)
  search.set('state', opts.state.trim())
  if (opts.limit != null) search.set('limit', String(opts.limit))
  return fetchAdminApi<MdrPeopleSearchPayload>(
    `/ops/drop/matching-contacts/search?${search.toString()}`,
  )
}

/**
 * Owner vertical matching review — `GET /ops/requests/{id}/verticals/{vertical}/matching-results`.
 * Optional `?system=` scopes a catalog system. Path stays request UUID + vertical
 * segment — never concatenate system into the URL.
 * Authorized via `user_vertical_assignments` (403 if the owner is not assigned that vertical).
 * Do not use `getDropMatchingResultDetail` as the owner path.
 */
export function getOwnerVerticalMatchingResults(
  requestId: string,
  vertical: string,
  system?: string,
) {
  const search = new URLSearchParams()
  if (system?.trim()) search.set('system', system.trim())
  const query = search.toString()
  return fetchAdminApi<MatchingResultDetail>(
    `/ops/requests/${encodeURIComponent(requestId)}/verticals/${encodeURIComponent(vertical)}/matching-results${query ? `?${query}` : ''}`,
  )
}

/** Soft-fail missing/legacy owner vertical payloads — 403 stays visible. */
export async function fetchOwnerVerticalMatchingDetailOptional(
  requestId: string,
  vertical: string,
  system?: string,
): Promise<MatchingResultDetail | null> {
  try {
    return await getOwnerVerticalMatchingResults(requestId, vertical, system)
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

export function postDropMatchingResultsBulkApprove(body: BulkApproveMatchingResultsInput) {
  return fetchAdminApi<BulkApproveMatchingResultsResult>('/ops/drop/matching-results/bulk-approve', {
    method: 'POST',
    body: JSON.stringify({
      decided_by: 'web-admin@habeas.com',
      ...body,
    }),
  })
}

export function postDropMatchingResultsBulkDecline(body: BulkApproveMatchingResultsInput) {
  return fetchAdminApi<{
    status: string
    match_type: MatchTypeFilter
    declined_count: number
    approval_ids: number[]
    request_ids: string[]
  }>('/ops/drop/matching-results/bulk-decline', {
    method: 'POST',
    body: JSON.stringify({
      decided_by: 'web-admin@habeas.com',
      ...body,
    }),
  })
}

/** CA DROP response_status codes operators confirm on Inbox fulfill. */
export type DropResponseStatusCode = 3 | 4 | 5

export const DROP_RESPONSE_STATUS_OPTIONS: {
  code: DropResponseStatusCode
  label: string
}[] = [
  { code: 3, label: 'Deleted' },
  { code: 4, label: 'Opted out' },
  { code: 5, label: 'Not found' },
]

/** Default DROP status from match type / count (same mapping as fulfillment stub). */
export function suggestedDropResponseStatus(
  matchType: string | null | undefined,
  matchCount?: number | null,
): DropResponseStatusCode {
  if (matchType === 'not_found' || matchCount === 0) return 5
  if (matchType === 'multi_match' || (matchCount != null && matchCount > 1)) return 4
  return 3
}

export function dropResponseStatusLabel(code: number | null | undefined): string {
  const found = DROP_RESPONSE_STATUS_OPTIONS.find((row) => row.code === code)
  return found ? `${found.code} ${found.label}` : code != null ? String(code) : '—'
}

export function postDropMatchingResultPromote(
  requestId: string,
  body?: {
    decision_reason?: string
    response_status?: DropResponseStatusCode
    dwids?: string[]
    vertical?: string | null
    system?: string | null
  },
) {
  return fetchAdminApi<{
    status: string
    request_id: string
    vertical?: string
    system?: string
    approval_id: number | null
    review_status?: string
    response_status?: number
    response_status_set?: boolean
    disposition?: { recorded?: boolean; reason?: string | null; vertical?: string } | null
  }>(`/ops/drop/matching-results/${encodeURIComponent(requestId)}/promote`, {
    method: 'POST',
    body: JSON.stringify({
      decided_by: 'web-admin@habeas.com',
      decision_reason: body?.decision_reason ?? 'fulfill — matching review approved',
      ...(body?.response_status != null
        ? { response_status: body.response_status }
        : {}),
      ...(body?.dwids != null ? { dwids: body.dwids } : {}),
      ...(body?.vertical?.trim() ? { vertical: body.vertical.trim() } : {}),
      ...(body?.system?.trim() ? { system: body.system.trim() } : {}),
    }),
  })
}

export function postDropMatchingResultDecline(
  requestId: string,
  body?: { decision_reason?: string; vertical?: string | null; system?: string | null },
) {
  return fetchAdminApi<{
    status: string
    request_id: string
    vertical?: string
    system?: string
    approval_id: number | null
    review_status?: string
  }>(`/ops/drop/matching-results/${encodeURIComponent(requestId)}/decline`, {
    method: 'POST',
    body: JSON.stringify({
      decided_by: 'web-admin@habeas.com',
      decision_reason: body?.decision_reason ?? 'decline — not fulfill-ready',
      ...(body?.vertical?.trim() ? { vertical: body.vertical.trim() } : {}),
      ...(body?.system?.trim() ? { system: body.system.trim() } : {}),
    }),
  })
}

export function postDropWorkflowAssign(body: {
  request_ids: string[]
  target_role?: WorkflowAssignmentTarget
  assignee_identity: string
}) {
  return fetchAdminApi<{
    status: string
    kind: string
    count: number
    request_ids: string[]
  }>('/ops/drop/workflow/assign', {
    method: 'POST',
    body: JSON.stringify({
      target_role: 'reviewer',
      decided_by: 'web-admin@habeas.com',
      ...body,
    }),
  })
}

export function postDropWorkflowAssignByMatchType(body: {
  match_type: MatchTypeFilter
  assignee_identity: string
  target_role?: WorkflowAssignmentTarget
}) {
  return fetchAdminApi<{
    status: string
    kind: string
    count: number
    batch_size: number
    ensured_count: number
    match_type: MatchTypeFilter
    request_ids: string[]
  }>('/ops/drop/workflow/assign-by-match-type', {
    method: 'POST',
    body: JSON.stringify({
      target_role: 'reviewer',
      decided_by: 'web-admin@habeas.com',
      ...body,
    }),
  })
}

export function postDropWorkflowEscalate(body: {
  request_ids: string[]
  target_role: 'legal' | 'data_owner'
  assignee_identity?: string
}) {
  return fetchAdminApi<{
    status: string
    kind: string
    count: number
    request_ids: string[]
  }>('/ops/drop/workflow/escalate', {
    method: 'POST',
    body: JSON.stringify({
      decided_by: 'web-admin@habeas.com',
      ...body,
    }),
  })
}

export function getDropWorkflowAssignments(params?: {
  assignee?: string
  target_role?: WorkflowAssignmentTarget
  status?: string
  limit?: number
}) {
  const search = new URLSearchParams()
  if (params?.assignee) search.set('assignee', params.assignee)
  if (params?.target_role) search.set('target_role', params.target_role)
  if (params?.status) search.set('status', params.status)
  if (params?.limit != null) search.set('limit', String(params.limit))
  const query = search.toString()
  return fetchAdminApi<{ assignments: WorkflowAssignmentSummary[]; count: number }>(
    `/ops/drop/workflow/assignments${query ? `?${query}` : ''}`,
  )
}

// --- Ops runs detail (U4) — append-only for parallel agent merges ---

export type RunTimelineStepStatus =
  | 'pending'
  | 'running'
  | 'waiting'
  | 'completed'
  | 'failed'
  | 'skipped'

export type RunTimelineStep = {
  key: string
  label: string
  status: RunTimelineStepStatus
  timestamp: string | null
  detail?: string | null
}

export type RunEvent = {
  id: string
  event_type: string
  occurred_at: string
  summary?: string | null
}

export type RunDetail = {
  run_id: string
  attempt_id: number
  job: string
  step?: string
  status: string
  request_id: string | null
  attempt_number?: number | null
  worker_id?: string | null
  started_at: string | null
  submitted_at?: string | null
  completed_at: string | null
  duration_seconds: number | null
  error_code?: string | null
  error_message?: string | null
  state?: string | null
  list_types?: string[] | null
  hash_index_run?: HashIndexRunMetrics | null
  timeline: RunTimelineStep[]
  events: RunEvent[]
  /** Full normalized API payload for DE inspection (counts/ids only). */
  raw?: Record<string, unknown>
}

/**
 * Canonical job names for admin-api /ops/runs (list filter + run_id prefix).
 * Accept short aliases from older UIs/APIs and normalize to attempt-table names.
 */
const RUN_JOB_CANONICAL: Record<string, string> = {
  drop_connector: 'drop_connector',
  connector: 'drop_connector',
  drop_ingestor: 'drop_ingestor',
  drop_ingest: 'drop_ingestor',
  ingest: 'drop_ingestor',
  matching: 'matching',
  hash_index_refresh: 'hash_index_refresh',
  hash_index: 'hash_index_refresh',
}

function toCanonicalRunJob(job: string | undefined): string | undefined {
  if (!job) return undefined
  return RUN_JOB_CANONICAL[job] ?? job
}

function fromApiRunJob(job: string): string {
  return toCanonicalRunJob(job) ?? job
}

export async function getRunDetail(job: string, attemptId: number) {
  // admin-api: GET /ops/runs/{run_id} where run_id is "{job}:{attempt_id}"
  const canonicalJob = toCanonicalRunJob(job) ?? job
  const runId = `${canonicalJob}:${attemptId}`
  const raw = await fetchAdminApi<Record<string, unknown>>(
    `/ops/runs/${encodeURIComponent(runId)}`,
  )
  return normalizeRunDetail(raw)
}

// --- Ops runs list (U4) ---

/** Prefer these pills across Workers / Runs / Dashboard. */
export type OpsTimeWindow = '8h' | '1w' | '3m' | 'custom' | '24h'

/** Workers UI windows — `8h`/`1w`/`3m` map to API `window` when supported; custom uses `since`. */
export type WorkersTimeWindow = '8h' | '1w' | '3m' | 'custom'

export function resolveRunsTimeParams(
  window: WorkersTimeWindow | OpsTimeWindow,
  since?: string,
): { window?: '8h' | '24h' | '1w' | '3m'; since?: string } {
  if (window === '8h' || window === '1w' || window === '24h' || window === '3m') {
    // Send both window and since for 3m so older admin-api (no 3m literal) still filters via since.
    if (window === '3m') {
      const anchor = new Date()
      anchor.setMonth(anchor.getMonth() - 3)
      return { window: '3m', since: since ?? anchor.toISOString() }
    }
    return { window }
  }
  if (window === 'custom' && since) {
    return { since }
  }
  return { window: '1w' }
}

export type RunSummary = {
  run_id: string
  job: string
  step: string
  status: string
  request_id: string | null
  started_at: string
  completed_at: string | null
  duration_seconds: number | null
  attempt_number: number
}

/** Normalize deployed envelope/field names onto the UI RunSummary contract. */
function normalizeRunSummary(raw: Record<string, unknown>): RunSummary {
  const apiJob = String(raw.job ?? '')
  const job = fromApiRunJob(apiJob)
  const id = raw.id ?? raw.attempt_id ?? raw.attempt_number
  const attemptNumber = typeof id === 'number' ? id : Number(id) || 0
  const runId =
    typeof raw.run_id === 'string' && raw.run_id
      ? raw.run_id
      : `${job}:${attemptNumber}`
  const startedAt = String(raw.started_at ?? raw.attempted_at ?? '')
  return {
    run_id: runId,
    job,
    step: String(raw.step ?? job),
    status: String(raw.status ?? ''),
    request_id: (raw.request_id as string | null | undefined) ?? null,
    started_at: startedAt,
    completed_at: (raw.completed_at as string | null | undefined) ?? null,
    duration_seconds:
      typeof raw.duration_seconds === 'number' ? raw.duration_seconds : null,
    attempt_number: attemptNumber,
  }
}

function normalizeTimelineStatus(value: unknown): RunTimelineStepStatus {
  const normalized = String(value ?? 'pending').toLowerCase()
  if (normalized === 'completed' || normalized === 'complete' || normalized === 'ok') {
    return 'completed'
  }
  if (normalized.includes('fail') || normalized.includes('error')) return 'failed'
  if (normalized === 'running' || normalized === 'in_flight' || normalized === 'claimed') {
    return 'running'
  }
  if (normalized === 'waiting' || normalized.includes('awaiting')) return 'waiting'
  if (normalized === 'skipped') return 'skipped'
  return 'pending'
}

function normalizeHashIndexRun(raw: unknown): HashIndexRunMetrics | null {
  if (!raw || typeof raw !== 'object') return null
  const row = raw as Record<string, unknown>
  if (row.run_status == null && row.run_started_at == null) return null
  return {
    run_status: (row.run_status as string | null | undefined) ?? null,
    run_started_at: (row.run_started_at as string | null | undefined) ?? null,
    run_finished_at: (row.run_finished_at as string | null | undefined) ?? null,
    rows_email: typeof row.rows_email === 'number' ? row.rows_email : null,
    rows_phone: typeof row.rows_phone === 'number' ? row.rows_phone : null,
    rows_ndz: typeof row.rows_ndz === 'number' ? row.rows_ndz : null,
    rematch_enqueued_count:
      typeof row.rematch_enqueued_count === 'number' ? row.rematch_enqueued_count : null,
    run_error_message: (row.run_error_message as string | null | undefined) ?? null,
  }
}

function normalizeRunDetail(raw: Record<string, unknown>): RunDetail {
  const summary = normalizeRunSummary(raw)
  const timelineRaw = Array.isArray(raw.timeline) ? raw.timeline : []
  const eventsRaw = Array.isArray(raw.events) ? raw.events : []
  const listTypes = Array.isArray(raw.list_types)
    ? raw.list_types.map(String)
    : null
  return {
    ...summary,
    attempt_id: summary.attempt_number,
    step: String(raw.step ?? summary.step ?? summary.job),
    worker_id: (raw.worker_id as string | null | undefined) ?? null,
    submitted_at: (raw.submitted_at as string | null | undefined) ?? null,
    error_code: (raw.error_code as string | null | undefined) ?? null,
    error_message:
      (raw.error_message as string | null | undefined) ??
      (raw.error_redacted as string | null | undefined) ??
      null,
    state: (raw.state as string | null | undefined) ?? null,
    list_types: listTypes,
    hash_index_run: normalizeHashIndexRun(raw.hash_index_run),
    timeline: timelineRaw.map((step, index) => {
      const row = step as Record<string, unknown>
      const key = String(row.key ?? row.event ?? row.step ?? `step-${index}`)
      return {
        key,
        label: String(row.label ?? row.event ?? row.step ?? key),
        status: normalizeTimelineStatus(row.status ?? 'completed'),
        timestamp:
          (row.timestamp as string | null | undefined) ??
          (row.at as string | null | undefined) ??
          null,
        detail: (row.detail as string | null | undefined) ?? null,
      }
    }),
    events: eventsRaw.map((event, index) => {
      const row = event as Record<string, unknown>
      return {
        id: String(row.id ?? `event-${index}`),
        event_type: String(row.event_type ?? row.kind ?? row.event ?? 'event'),
        occurred_at: String(row.occurred_at ?? row.at ?? ''),
        summary:
          (row.summary as string | null | undefined) ??
          (row.detail as string | null | undefined) ??
          null,
      }
    }),
    raw,
  }
}

export async function listRuns(params?: {
  job?: string
  status?: string
  request_id?: string
  process_id?: number
  window?: OpsTimeWindow
  since?: string
  limit?: number
  offset?: number
}) {
  const search = new URLSearchParams()
  const apiJob = toCanonicalRunJob(params?.job)
  if (apiJob) search.set('job', apiJob)
  if (params?.status) search.set('status', params.status)
  if (params?.request_id) search.set('request_id', params.request_id)
  if (params?.process_id != null) search.set('process_id', String(params.process_id))
  if (params?.window && params.window !== 'custom') {
    search.set('window', params.window)
  }
  if (params?.since) search.set('since', params.since)
  if (params?.limit != null) search.set('limit', String(params.limit))
  if (params?.offset != null) search.set('offset', String(params.offset))
  const query = search.toString()
  const raw = await fetchAdminApi<unknown>(`/ops/runs${query ? `?${query}` : ''}`)
  const rows = Array.isArray(raw)
    ? raw
    : Array.isArray((raw as { runs?: unknown }).runs)
      ? ((raw as { runs: unknown[] }).runs)
      : []
  return rows.map((row) => normalizeRunSummary(row as Record<string, unknown>))
}

// --- Ops project logs (attempt tables + admin audit) ---

export type OpsLogSeverity = 'ERROR' | 'WARNING' | 'INFO'
export type OpsLogSource = 'attempt' | 'audit'

export type OpsLogEntry = {
  id: string
  timestamp: string
  severity: OpsLogSeverity
  resource: string
  source: OpsLogSource
  message: string
  status: string | null
  step: string | null
  request_id: string | null
  run_id: string | null
  actor: string | null
  result_status: number | null
  error_code: string | null
}

function normalizeOpsLogEntry(raw: Record<string, unknown>): OpsLogEntry {
  const severityRaw = String(raw.severity ?? 'INFO').toUpperCase()
  const severity: OpsLogSeverity =
    severityRaw === 'ERROR' || severityRaw === 'WARNING' || severityRaw === 'INFO'
      ? severityRaw
      : 'INFO'
  const sourceRaw = String(raw.source ?? 'attempt')
  return {
    id: String(raw.id ?? ''),
    timestamp: String(raw.timestamp ?? ''),
    severity,
    resource: String(raw.resource ?? ''),
    source: sourceRaw === 'audit' ? 'audit' : 'attempt',
    message: String(raw.message ?? ''),
    status: (raw.status as string | null | undefined) ?? null,
    step: (raw.step as string | null | undefined) ?? null,
    request_id: (raw.request_id as string | null | undefined) ?? null,
    run_id: (raw.run_id as string | null | undefined) ?? null,
    actor: (raw.actor as string | null | undefined) ?? null,
    result_status: typeof raw.result_status === 'number' ? raw.result_status : null,
    error_code: (raw.error_code as string | null | undefined) ?? null,
  }
}

export async function listOpsLogs(params?: {
  severity?: OpsLogSeverity | OpsLogSeverity[]
  resource?: string
  source?: OpsLogSource
  q?: string
  window?: OpsTimeWindow
  since?: string
  limit?: number
  offset?: number
}) {
  const search = new URLSearchParams()
  if (params?.severity) {
    const value = Array.isArray(params.severity)
      ? params.severity.join(',')
      : params.severity
    search.set('severity', value)
  }
  if (params?.resource) search.set('resource', params.resource)
  if (params?.source) search.set('source', params.source)
  if (params?.q) search.set('q', params.q)
  if (params?.window && params.window !== 'custom') {
    search.set('window', params.window)
  }
  if (params?.since) search.set('since', params.since)
  if (params?.limit != null) search.set('limit', String(params.limit))
  if (params?.offset != null) search.set('offset', String(params.offset))
  const query = search.toString()
  const raw = await fetchAdminApi<unknown>(`/ops/logs${query ? `?${query}` : ''}`)
  const rows = Array.isArray(raw) ? raw : []
  return rows.map((row) => normalizeOpsLogEntry(row as Record<string, unknown>))
}

// --- Request journey + needs attention (U5) ---

export type JourneyStageStatus =
  | 'not_started'
  | 'skipped'
  | 'in_progress'
  | 'waiting'
  | 'complete'
  | 'failed'

export type JourneyStage = {
  stage: string
  label: string
  status: JourneyStageStatus
  attempted_at: string | null
  completed_at: string | null
  blocker: string | null
}

export type RequestJourneyResponse = {
  request_id: string
  intake_source: string
  received_at: string | null
  current_stage: string
  blocker: string | null
  stages: JourneyStage[]
  /** CSV member linking this request into a bulk ZIP process. */
  source_csv_filename?: string | null
  /** drop_connector download attempt id (bulk process key). */
  bulk_process_id?: number | null
  /** CA DROP response_status when fulfillment has written it. */
  response_status?: number | null
}

export type NeedsAttentionAssignment = {
  target_role: string | null
  kind: string | null
  assignee_identity: string | null
}

export type NeedsAttentionItemKind =
  | 'matching'
  | 'triage'
  | 'escalations'
  | 'notice'
  | 'delivery'

export type NeedsAttentionKind = NeedsAttentionItemKind | 'all'

export type NeedsAttentionItem = {
  request_id: string
  reason: string
  kind?: NeedsAttentionItemKind
  current_stage: string
  intake_source: string
  received_at: string | null
  requested_at: string | null
  approval_id?: number | null
  matched?: boolean | null
  match_count?: number | null
  match_type?: string | null
  /** Computed at read time from match_count (0→5, 1→3, N→4). */
  recommended_response_status?: number | null
  /** CA DROP response_status when already fulfilled (notice rows). */
  response_status?: number | null
  matched_via?: string | null
  requestor_state?: string | null
  review_status?: string | null
  assignment?: NeedsAttentionAssignment | null
  /** Per-vertical matching review scope (data_owner inbox) — not request ownership. */
  vertical?: string | null
  vertical_label?: string | null
  system?: string
  system_id?: string
  system_label?: string
  color_token?: string
  /**
   * Client coalesce (owner / lab-as-owner) — systems on this request.
   * Never a POST key.
   */
  connections?: Array<{
    system: string | null
    system_label?: string | null
    vertical?: string | null
    color_token?: string | null
    current_stage?: string | null
    match_type?: string | null
    kind?: string | null
    matched_via?: string | null
  }>
  /** Client coalesce — unioned email/phone/ndz chips. */
  channels?: Array<'email' | 'phone' | 'ndz'>
  /** drop_connector download attempt id — batch key for inbox threads */
  bulk_process_id?: number | null
  /** ZIP member name — fallback batch key when download ledger is missing */
  source_csv_filename?: string | null
}

export type NeedsAttentionFilterOption = {
  id: string
  label: string
  vertical?: string
  color_token?: string
}

export type NeedsAttentionResponse = {
  items: NeedsAttentionItem[]
  kind?: NeedsAttentionKind
  /** Full filtered/union count for this kind (up to the server's safety cap) — use for pagination, not just items.length. */
  total?: number
  limit?: number
  offset?: number
  filter_verticals?: NeedsAttentionFilterOption[]
  filter_systems?: NeedsAttentionFilterOption[]
}

export type RequestComment = {
  id: number
  request_id: string
  author_user_id: number
  actor: string
  body: string
  occurred_at: string
}

export function getRequestJourney(requestId: string) {
  return fetchAdminApi<RequestJourneyResponse>(
    `/ops/requests/${encodeURIComponent(requestId)}/journey`,
  )
}

// --- Journey workbench (U4 · KTD2 / KTD3) ---
//
// Four-stage legal/admin detail chrome (Ingest → Matching → Fulfillment →
// Notice) with Matching/Fulfillment split into per-vertical clusters. This
// is a separate DTO from `RequestJourneyResponse` above — the ops fine
// journey stays untouched; the workbench is consumed by the new detail
// chrome UI (U5) only.

export type WorkbenchStageKey = 'ingest' | 'matching' | 'fulfillment' | 'notice'

export type WorkbenchStage = {
  stage: WorkbenchStageKey
  label: string
  status: JourneyStageStatus
  blocker: string | null
}

export type WorkbenchStepAttempts = {
  step: string
  status: JourneyStageStatus
  attempt_count: number
  last_attempt_status: string | null
  attempted_at: string | null
  completed_at: string | null
  error_code: string | null
}

export type WorkbenchVerticalRow = {
  vertical: string
  label: string
  live: boolean
  actionable: boolean
  matching_status: JourneyStageStatus
  disposition_status: number | null
  selected_dwid_count: number | null
  kicked_off: boolean
  identity_required: boolean
  identity_verified: boolean | null
  fulfillment_status: JourneyStageStatus | null
  fulfillment_steps: WorkbenchStepAttempts[]
  blocker: string | null
}

export type WorkbenchNoticeSummary = {
  status: JourneyStageStatus
  ready: boolean
  blocker: string | null
  response_status: number | null
}

export type RequestJourneyWorkbenchResponse = {
  request_id: string
  intake_source: string
  request_type: string
  stages: WorkbenchStage[]
  current_stage: WorkbenchStageKey
  /** KD4/R3 — Matching and Fulfillment both read in_progress simultaneously. */
  split_posture: boolean
  matching_cluster: WorkbenchVerticalRow[]
  fulfillment_cluster: WorkbenchVerticalRow[]
  notice: WorkbenchNoticeSummary
}

export type WorkbenchVerticalBatchRow = {
  vertical: string
  label: string
  live: boolean
  actionable: boolean
  matching_status: JourneyStageStatus
  fulfillment_status: JourneyStageStatus | null
  /** status → count of member requests at that status (worst-first rollup). */
  member_status_counts: Record<string, number>
}

export type BatchJourneyWorkbenchResponse = {
  bulk_process_id: number
  request_count: number
  member_request_ids: string[]
  stages: WorkbenchStage[]
  current_stage: WorkbenchStageKey
  split_posture: boolean
  matching_cluster: WorkbenchVerticalBatchRow[]
  fulfillment_cluster: WorkbenchVerticalBatchRow[]
}

export function getRequestJourneyWorkbench(requestId: string) {
  return fetchAdminApi<RequestJourneyWorkbenchResponse>(
    `/ops/requests/${encodeURIComponent(requestId)}/journey-workbench`,
  )
}

export function getBatchJourneyWorkbench(bulkProcessId: number) {
  return fetchAdminApi<BatchJourneyWorkbenchResponse>(
    `/ops/requests/batches/${encodeURIComponent(String(bulkProcessId))}/journey-workbench`,
  )
}

export type FulfillmentKickoffResponse = {
  request_id: string
  vertical: string
  kickoff_status: 'approved' | 'already_approved' | string
  approval_id: number | null
  disposition_updated: boolean
}

/** Legal starts fulfillment for one live vertical (R11 / KD6, U2 gate). */
export function postFulfillmentKickoff(
  requestId: string,
  body: { vertical: string; status?: number; dwids?: string[]; decision_reason?: string },
) {
  return fetchAdminApi<FulfillmentKickoffResponse>(
    `/requests/${encodeURIComponent(requestId)}/fulfillment/kickoff`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  )
}

/** KD37 named statuses — SaaS owner Inbox after Legal kickoff (U17 / U18). */
export type FulfillmentOwnerStatus =
  | 'in_progress'
  | 'completed_in_source'
  | 'blocked'
  | 'assign_to_legal'

export type FulfillmentOwnerStatusBody = {
  status: FulfillmentOwnerStatus
  comment?: string
}

export type FulfillmentOwnerStatusResponse = {
  request_id: string
  vertical: string
  owner_status: FulfillmentOwnerStatus
  attempt_id: number
  attempt_status: string
  assigned_to_legal: boolean
  comment_recorded: boolean
}

/** Assigned SaaS owner sets KD37 status after Legal kickoff. */
export function patchFulfillmentOwnerStatus(
  requestId: string,
  vertical: string,
  body: FulfillmentOwnerStatusBody,
) {
  return fetchAdminApi<FulfillmentOwnerStatusResponse>(
    `/requests/${encodeURIComponent(requestId)}/fulfillment/${encodeURIComponent(vertical)}/owner-status`,
    {
      method: 'PATCH',
      body: JSON.stringify(body),
    },
  )
}

export function ownerFulfillmentItemFromRequest(record: RequestRecord): NeedsAttentionItem {
  return {
    request_id: record.id,
    reason: 'fulfillment.owner',
    current_stage: 'fulfillment',
    intake_source: record.intake_source,
    received_at: record.received_at,
    requested_at: record.received_at,
    requestor_state: record.requestor_state ?? null,
  }
}

export function ownerFulfillmentItemFromApproval(
  approval: ApprovalRecord,
): NeedsAttentionItem {
  return {
    request_id: approval.request_id,
    reason: 'fulfillment.kickoff',
    current_stage: 'fulfillment',
    intake_source: 'drop',
    received_at: null,
    requested_at: null,
  }
}

/** Prefer list-request metadata; keep kickoff reason when an approval also matched. */
export function mergeOwnerFulfillmentItems(
  fromRequests: NeedsAttentionItem[],
  fromApprovals: NeedsAttentionItem[],
): NeedsAttentionItem[] {
  const byId = new Map<string, NeedsAttentionItem>()
  for (const item of fromApprovals) {
    if (!item.request_id) continue
    byId.set(item.request_id, item)
  }
  for (const item of fromRequests) {
    if (!item.request_id) continue
    const existing = byId.get(item.request_id)
    byId.set(item.request_id, existing ? { ...existing, ...item } : item)
  }
  return [...byId.values()]
}

async function listApprovedFulfillmentKickoffs(limit: number): Promise<ApprovalRecord[]> {
  const search = new URLSearchParams({
    action_type: 'fulfillment.kickoff',
    status: 'approved',
    limit: String(Math.min(200, Math.max(1, limit))),
  })
  return fetchAdminApi<ApprovalRecord[]>(`/approvals?${search}`, {
    timeoutMs: OPS_QUERY_TIMEOUT_MS,
  })
}

/**
 * Owner-safe Fulfillment queue — do not call `getLegalNeedsAttention` (403).
 * `getNeedsAttention` has no fulfillment kind; All-requests `stage=fulfillment`
 * plus approved kickoff gates cover SaaS legs that have no open attempt yet.
 */
export async function getOwnerFulfillmentNeedsAttention(params?: {
  limit?: number
}): Promise<NeedsAttentionResponse> {
  const limit = params?.limit ?? 200
  const [page, approvals] = await Promise.all([
    listRequests({
      stage: 'fulfillment',
      limit,
      offset: 0,
      timeoutMs: OPS_QUERY_TIMEOUT_MS,
    }),
    listApprovedFulfillmentKickoffs(limit).catch((error: unknown) => {
      if (error instanceof Error && /Admin API 403/.test(error.message)) {
        return [] as ApprovalRecord[]
      }
      throw error
    }),
  ])
  const items = mergeOwnerFulfillmentItems(
    page.items.map(ownerFulfillmentItemFromRequest),
    approvals.map(ownerFulfillmentItemFromApproval),
  )
  return {
    items: items.slice(0, limit),
    kind: 'all',
    total: items.length,
    limit,
    offset: 0,
  }
}

export function getNeedsAttention(
  limitOrParams?:
    | number
    | {
        limit?: number
        offset?: number
        kind?: NeedsAttentionKind
        assignee?: string
        vertical?: string
        system?: string
        source?: string
        step?: string
      },
) {
  const params =
    typeof limitOrParams === 'number'
      ? { limit: limitOrParams }
      : (limitOrParams ?? {})
  const search = new URLSearchParams()
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  if (params.kind) search.set('kind', params.kind)
  if (params.assignee) search.set('assignee', params.assignee)
  if (params.vertical?.trim()) search.set('vertical', params.vertical.trim())
  if (params.system?.trim()) search.set('system', params.system.trim())
  if (params.source?.trim()) search.set('source', params.source.trim())
  if (params.step?.trim()) search.set('step', params.step.trim())
  const query = search.toString()
  return fetchAdminApi<NeedsAttentionResponse>(
    `/ops/requests/needs-attention${query ? `?${query}` : ''}`,
    { timeoutMs: OPS_QUERY_TIMEOUT_MS },
  )
}

/**
 * Data-owner matching inbox — `GET /ops/requests/needs-attention?kind=matching`.
 * Server uses `list_owner_matching_needs_attention` from `user_vertical_assignments`
 * (one row per `(request_id, vertical, system)`). Do not send `assignee` — data-owner
 * calls ignore `workflow.assignment`.
 */
export function getOwnerMatchingNeedsAttention(params?: {
  limit?: number
  offset?: number
  vertical?: string
  system?: string
  source?: string
  step?: string
}) {
  return getNeedsAttention({
    limit: params?.limit,
    offset: params?.offset,
    kind: 'matching',
    vertical: params?.vertical,
    system: params?.system,
    source: params?.source,
    step: params?.step,
  })
}

/** Tasks tab: `item.vertical ∈ me.verticals` — not `workflow.assignment`. */
export function isOwnerVerticalTask(
  item: Pick<NeedsAttentionItem, 'vertical'>,
  verticals: readonly string[] | null | undefined,
): boolean {
  const vertical = item.vertical?.trim()
  if (!vertical) return false
  return (verticals ?? []).some((id) => id.trim() === vertical)
}

/** Legal case lanes only — excludes matching.review so ops volume cannot crowd Triage out. */
export const LEGAL_INBOX_KINDS: NeedsAttentionItemKind[] = [
  'triage',
  'escalations',
  'notice',
  'delivery',
]

/**
 * Legal inbox — server paginates: one admin-api call per legal kind, each
 * already offset/limited, merged and re-sorted client-side across the (small,
 * bounded) per-kind pages. Replaces the old "fetch limit=1000 per kind, page
 * client-side" pattern — legal no longer pulls 1000×4 rows to show one page.
 */
export async function getLegalNeedsAttention(params?: {
  limit?: number
  offset?: number
  assignee?: string
}): Promise<NeedsAttentionResponse> {
  const limit = params?.limit ?? 30
  const offset = params?.offset ?? 0
  const results = await Promise.all(
    LEGAL_INBOX_KINDS.map((kind) =>
      getNeedsAttention({
        // Fetch enough of each kind's own ordering to cover this page after
        // the cross-kind merge/re-sort below — bounded by the same 1000 cap
        // admin-api enforces per kind.
        limit: Math.min(1000, offset + limit),
        kind,
        assignee: params?.assignee,
      }),
    ),
  )
  const merged = results.flatMap((result) => result.items)
  merged.sort((a, b) =>
    (a.requested_at || a.received_at || '').localeCompare(
      b.requested_at || b.received_at || '',
    ),
  )
  const total = results.reduce((sum, result) => sum + (result.total ?? result.items.length), 0)
  const items = merged.slice(offset, offset + limit)
  return { items, kind: 'all', total, limit, offset }
}

export type LegalPortfolioWindowDays = '7' | '30' | '90' | 'ytd' | 'all'

export type LegalPortfolio = {
  source_buckets: { drop: number; other: number }
  type_counts: Array<{ request_type: string; count: number }>
  stage_matrix: Array<{
    stage: string
    in_queue: number
    in_progress: number
    complete: number
  }>
  pipeline_stages: Array<{ stage: string; count: number }>
  data_owner_queues: Array<{
    assignee_identity: string | null
    pending_count: number
    outreach_hint: string | null
  }>
  warnings: Array<{ code: string; message: string; count: number }>
  schedule_excerpt: {
    label: string
    next_run_at: string | null
    cadence: string | null
  } | null
  /** Variation B fields — absent until admin-api with legal Home enrichment is deployed. */
  fulfillment_batches?: Array<{
    batch_key: string
    source_label: string
    received_at: string
    request_count: number
  }>
  stage_reach_counts?: Array<{
    stage: string
    reached_count: number
    dropped_count: number
  }>
  heatmap_cells?: Array<{
    intake_source: string
    request_type: string
    count: number
  }>
  deadline_risk?: {
    overdue: number
    due_within_7_days: number
    on_track: number
    closed_ytd: number
  }
  operations_pulse?: {
    open_assigned_to_you: number
    open_team_wide: number
    sla_at_risk: number
    overdue: number
    median_age_hours: number
  }
}

export function getLegalPortfolio(params?: {
  window_days?: LegalPortfolioWindowDays
  batch_key?: string
}) {
  const search = new URLSearchParams()
  if (params?.window_days) search.set('window_days', params.window_days)
  if (params?.batch_key) search.set('batch_key', params.batch_key)
  const qs = search.toString()
  return fetchAdminApi<LegalPortfolio>(`/legal/home/portfolio${qs ? `?${qs}` : ''}`)
}

export type LegalSlaSettings = {
  data_owner_review_days: number
  legal_pre_fulfillment_days: number
  fulfillment_days: number
  lifecycle_days: number
  updated_at: string | null
}

export function getLegalSlaSettings() {
  return fetchAdminApi<LegalSlaSettings>('/legal/settings/sla')
}

export function patchLegalSlaSettings(body: Partial<LegalSlaSettings>) {
  return fetchAdminApi<LegalSlaSettings>('/legal/settings/sla', {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export type LegalTeamMember = { email: string; active: boolean; added_at: string | null }

export function getLegalTeam() {
  return fetchAdminApi<LegalTeamMember[]>('/legal/team')
}

export function addLegalTeamMember(email: string) {
  return fetchAdminApi<LegalTeamMember>('/legal/team', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export function removeLegalTeamMember(email: string) {
  return fetchAdminApi<{ status: string }>(`/legal/team/${encodeURIComponent(email)}`, {
    method: 'DELETE',
  })
}

export type LegalOperator = { email: string; kind: string }

export function getLegalOperators() {
  return fetchAdminApi<LegalOperator[]>('/legal/operators')
}

export function postTriageBulkReject(body: {
  request_ids: string[]
  response_status?: number
  decision_reason?: string | null
}) {
  return fetchAdminApi<{
    status: string
    count: number
    request_ids: string[]
    results: Array<{
      request_id: string
      response_status: number
      response_status_set: boolean
      assignment_closed: boolean
    }>
  }>('/ops/drop/workflow/triage/bulk-reject', {
    method: 'POST',
    body: JSON.stringify({
      decided_by: 'web-admin@habeas.com',
      response_status: 2,
      ...body,
    }),
  })
}

export function postTriageSendToMatching(body: {
  request_ids: string[]
  decision_reason?: string | null
}) {
  return fetchAdminApi<{
    status: string
    count: number
    request_ids: string[]
    enqueued: string[]
  }>('/ops/drop/workflow/triage/send-to-matching', {
    method: 'POST',
    body: JSON.stringify({
      decided_by: 'web-admin@habeas.com',
      ...body,
    }),
  })
}

export function postNoticeApprove(body: {
  request_ids: string[]
  decision_reason?: string | null
}) {
  return fetchAdminApi<{
    status: string
    count: number
    request_ids: string[]
    results: Array<{
      request_id: string
      notice_review_status_set: boolean
      assignment_closed: boolean
    }>
  }>('/ops/drop/workflow/notice/approve', {
    method: 'POST',
    body: JSON.stringify({
      decided_by: 'web-admin@habeas.com',
      ...body,
    }),
  })
}

export type RouteTriageCondition = {
  requestor_state_not_in?: string[]
  state_in?: string[]
}

export type RouteTriageRule = {
  id: number
  action_type: string
  requires_approval: boolean
  approver_role: string | null
  condition_jsonb: RouteTriageCondition
  rationale: string
  effective_from: string | null
  effective_to: string | null
  created_by: string
  created_at: string | null
}

export function getRouteTriageCondition() {
  return fetchAdminApi<RouteTriageRule>('/ops/drop/workflow/conditions/route-triage')
}

export function putRouteTriageCondition(body: {
  condition_jsonb: RouteTriageCondition
  rationale: string
}) {
  return fetchAdminApi<{ status: string; rule: RouteTriageRule }>(
    '/ops/drop/workflow/conditions/route-triage',
    {
      method: 'PUT',
      body: JSON.stringify({
        decided_by: 'web-admin@habeas.com',
        ...body,
      }),
    },
  )
}

export function getRequestComments(requestId: string, limit?: number) {
  const search = new URLSearchParams()
  if (limit != null) search.set('limit', String(limit))
  const query = search.toString()
  return fetchAdminApi<RequestComment[]>(
    `/ops/requests/${encodeURIComponent(requestId)}/comments${query ? `?${query}` : ''}`,
  )
}

export function postRequestComment(requestId: string, body: string) {
  return fetchAdminApi<RequestComment>(
    `/ops/requests/${encodeURIComponent(requestId)}/comments`,
    {
      method: 'POST',
      body: JSON.stringify({ body }),
    },
  )
}

export function postRequestClose(
  requestId: string,
  body?: { note?: string; drop_response_status?: DropResponseStatusCode },
) {
  return fetchAdminApi<{
    request_id: string
    closed_at: string
    closed_by: string | null
    already_closed: boolean
    drop_response_status_set: boolean
  }>(`/ops/requests/${encodeURIComponent(requestId)}/close`, {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
  })
}

export type TimelineEntry = {
  at: string
  kind: string
  actor: string | null
  summary: string
  meta: Record<string, unknown>
}

export type RequestTimeline = {
  request_id: string
  entries: TimelineEntry[]
}

export function getRequestTimeline(requestId: string) {
  return fetchAdminApi<RequestTimeline>(
    `/ops/requests/${encodeURIComponent(requestId)}/timeline`,
  )
}

export type EmailTemplateRecord = {
  id: number
  slug: string
  subject: string
  body: string
  placeholder_schema: string[]
  active: boolean
}

export function listEmailTemplates() {
  return fetchAdminApi<EmailTemplateRecord[]>('/requests/email-templates')
}

/** Request-type -> default slug (KD11 variables curated per role-visible fields). */
export type EmailTemplateType = 'access' | 'delete' | 'opt_out' | 'combined' | 'general'

export type EmailTemplateTypeInfo = {
  type: EmailTemplateType
  slug: string
  variables: string[]
}

export function listEmailTemplateTypes() {
  return fetchAdminApi<EmailTemplateTypeInfo[]>('/requests/email-templates/types')
}

export type EmailTemplateUpsertInput = {
  subject: string
  body: string
  placeholder_schema?: string[]
  active?: boolean
}

export function upsertEmailTemplate(slug: string, body: EmailTemplateUpsertInput) {
  return fetchAdminApi<EmailTemplateRecord>(
    `/requests/email-templates/${encodeURIComponent(slug)}`,
    {
      method: 'PUT',
      body: JSON.stringify({ placeholder_schema: [], active: true, ...body }),
    },
  )
}

export type RenderedEmailTemplate = {
  slug: string
  subject: string
  body: string
}

export function renderEmailTemplate(
  slug: string,
  context: Record<string, string> = {},
  requestId?: string,
) {
  return fetchAdminApi<RenderedEmailTemplate>('/requests/email-templates/render', {
    method: 'POST',
    body: JSON.stringify({ slug, context, request_id: requestId ?? null }),
  })
}

// --- U7: request document/attachment client helpers (R20/KD12/KTD9) --------
// Roles: super_admin, admin, legal, data_owner may all upload/list/download.

export type RequestDocumentRecord = {
  id: string
  request_id: string
  filename: string
  content_type: string
  uploaded_by: string
  uploaded_at: string
}

export function listRequestDocuments(requestId: string) {
  return fetchAdminApi<RequestDocumentRecord[]>(
    `/requests/${encodeURIComponent(requestId)}/documents`,
  )
}

export async function uploadRequestDocument(requestId: string, file: File) {
  await refreshAdminApiUserTokenIfNeeded()
  const headers = adminApiAuthHeaders({ Accept: 'application/json' })
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(
    adminApiRequestUrl(`/requests/${encodeURIComponent(requestId)}/documents`),
    { method: 'POST', headers, body: form },
  )
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`Admin API ${response.status}: ${detail || response.statusText}`)
  }
  return (await response.json()) as RequestDocumentRecord
}

/** Fetches the file as a Blob for direct download (caller drives the `<a>`/save-as flow). */
export async function downloadRequestDocument(
  requestId: string,
  documentId: string,
): Promise<Blob> {
  await refreshAdminApiUserTokenIfNeeded()
  const headers = adminApiAuthHeaders()
  const response = await fetch(
    adminApiRequestUrl(
      `/requests/${encodeURIComponent(requestId)}/documents/${encodeURIComponent(documentId)}/download`,
    ),
    { headers },
  )
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`Admin API ${response.status}: ${detail || response.statusText}`)
  }
  return response.blob()
}

/** Hard-delete a request document (KTD9: uploader or admin/super_admin). */
export async function deleteRequestDocument(
  requestId: string,
  documentId: string,
): Promise<void> {
  await refreshAdminApiUserTokenIfNeeded()
  const headers = adminApiAuthHeaders({ Accept: 'application/json' })
  const response = await fetch(
    adminApiRequestUrl(
      `/requests/${encodeURIComponent(requestId)}/documents/${encodeURIComponent(documentId)}`,
    ),
    { method: 'DELETE', headers },
  )
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`Admin API ${response.status}: ${detail || response.statusText}`)
  }
}

/**
 * Catalog / write `system_id` values.
 * Axios HQ is `axios_hq`. Retracted `axios_headquarters` is unknown on write
 * paths (`unknown_system`) — display aliases it; do not send it on create/mode.
 */
export type IntegrationSystemId =
  | 'paylocity'
  | 'lever'
  | 'auth0'
  | 'google_sheets'
  | 'alumni_google_sheet'
  | 'contact_us_google_sheet'
  | 'bizdev_contacts'
  | 'hr_alumni'
  | 'axios_hq'
  | 'cassandra'

/** Catalog/display system id for Axios HQ. */
export const AXIOS_HQ_CATALOG_SYSTEM_ID: IntegrationSystemId = 'axios_hq'

/** Retracted worker/legacy slug — not a write `system_id`. */
export const AXIOS_HQ_RETRACTED_SYSTEM_ID = 'axios_headquarters'

export function isRetractedConnectionSystem(system: string | null | undefined): boolean {
  return (system ?? '').trim().toLowerCase() === AXIOS_HQ_RETRACTED_SYSTEM_ID
}

/**
 * Display/catalog id. Maps retracted Axios HQ slug → `axios_hq`.
 * Do not use the result as a create/mode write body when the input was retracted.
 */
export function catalogDisplaySystemId(system: string | null | undefined): string {
  const id = (system ?? '').trim().toLowerCase()
  if (id === AXIOS_HQ_RETRACTED_SYSTEM_ID) return AXIOS_HQ_CATALOG_SYSTEM_ID
  return id
}

export type ConnectionDisplayStatus =
  | 'needs_setup'
  | 'action_required'
  | 'needs_refresh'
  | 'connected'
  | 'view_only'

export type ConnectionRecord = {
  id: string
  system: IntegrationSystemId
  display_name: string
  status:
    | 'pending'
    | 'invited'
    | 'connected'
    | 'failed'
    | 'revoked'
    | 'infra_pending'
  owner_email: string | null
  secret_resource_name: string | null
  last_tested_at: string | null
  last_test_ok: boolean | null
  last_test_detail: string | null
  created_by: string
  created_at: string
  updated_at: string
  metadata: Record<string, unknown>
  /** Gated matching UX status (KD18) — prefer over raw `status` for chips. */
  display_status?: ConnectionDisplayStatus | string | null
  gate_code?: string | null
  gate_allowed?: boolean | null
}

export type ConnectionInviteCreateResponse = {
  invite_id: string
  owner_email: string
  expires_at: string
  invite_url: string
  raw_token: string
}

export type ConnectionSystemsPayload = {
  systems: Array<{
    system_id: IntegrationSystemId
    display_label: string
    invite_allowed: boolean
    credential_fields: Array<{
      id: string
      label: string
      input_type: 'password' | 'text' | 'url'
      required: boolean
      help: string | null
    }>
    trust_copy: string
  }>
}

export type ConnectPreviewPayload = {
  system: IntegrationSystemId
  display_name: string
  owner_email: string
  fields: Array<{
    id: string
    label: string
    input_type: 'password' | 'text' | 'url'
    required: boolean
    help: string | null
  }>
  trust_copy: string
  expires_at: string
}

export type ConnectRedeemResponse = {
  status: string
  test_ok: boolean
  detail: string | null
}

/** Allowlisted redeem/test detail codes — never echo vendor bodies in UI. */
export type ConnectTestDetailCode =
  | 'stub_ok'
  | 'ok'
  | 'paylocity_ok'
  | 'lever_ok'
  | 'auth0_ok'
  | 'google_sheets_ok'
  | 'alumni_google_sheet_ok'
  | 'contact_us_google_sheet_ok'
  | 'axios_hq_ok'
  | 'axios_headquarters_ok'
  | 'upload_ok'
  | 'auth_failed'
  | 'lever_unauthorized'
  | 'lever_forbidden'
  | 'unreachable'
  | 'invalid_credentials'
  | 'invalid_config'
  | 'missing_credentials'
  | 'unknown_system'
  | 'infra_only'
  | 'unknown_error'
  | 'failed'
  | 'upload_missing_headers'
  | 'upload_needs_mapping'
  | 'upload_no_usable_rows'
  | 'upload_rows_rejected'
  | 'upload_invalid_format'
  | 'upload_invalid_delimiter'

const CONNECT_SYSTEM_LABELS: Record<IntegrationSystemId, string> = {
  paylocity: 'Paylocity',
  lever: 'Lever',
  auth0: 'Auth0',
  google_sheets: 'Google Sheets',
  alumni_google_sheet: 'HR alumni Google Sheet',
  contact_us_google_sheet: 'Contact Us Google Sheet',
  bizdev_contacts: 'BizDev Contacts',
  hr_alumni: 'HR Alumni List',
  axios_hq: 'Axios HQ',
  cassandra: 'System A',
}

const CONNECT_TEST_SUCCESS_DESCRIPTIONS: Record<string, string> = {
  paylocity_ok: 'Paylocity API credentials were verified successfully.',
  lever_ok: 'Lever API credentials were verified successfully.',
  auth0_ok: 'Auth0 credentials were verified successfully.',
  google_sheets_ok: 'Google Sheets connection was verified successfully.',
  alumni_google_sheet_ok: 'HR alumni Google Sheet connection was verified successfully.',
  contact_us_google_sheet_ok: 'Contact Us Google Sheet connection was verified successfully.',
  axios_hq_ok: 'Axios HQ upload was validated successfully.',
  axios_headquarters_ok: 'Axios HQ upload was validated successfully.',
  upload_ok: 'Upload file was validated successfully.',
  stub_ok: 'Connection test completed successfully.',
  ok: 'Connection test completed successfully.',
}

const CONNECT_TEST_FAILURE_MESSAGES: Record<string, string> = {
  auth_failed: 'Authentication failed. Check the credentials and try again.',
  lever_unauthorized:
    'Lever rejected the API key (unauthorized). Confirm you pasted the Lever API key — not your password and not the Postings API key — then try again.',
  lever_forbidden:
    'Lever accepted the key but denied Users access (forbidden). Enable Users read/list on the Lever API key (not Postings-only) and regenerate if permissions cannot be changed.',
  unreachable: 'Could not reach the service. Try again in a few minutes.',
  invalid_credentials: 'The credentials could not be verified. Check the values and try again.',
  invalid_config: 'The connection settings look incorrect. Check the fields and try again.',
  missing_credentials: 'Connection test could not run. Check the fields and try again.',
  unknown_system: 'Connection test failed. Ask your Habeas contact to send a new invite.',
  infra_only: 'This system is provisioned by Habeas Infrastructure, not through this form.',
  unknown_error: 'Connection test failed. Check the values and try again.',
  failed: 'Connection test failed. Check the values and try again.',
  upload_missing_headers:
    'Upload is missing required template headers. Download the Habeas CSV template and match the column names exactly.',
  upload_needs_mapping:
    'Column names do not match the Habeas template. Map first name, last name, and email, then upload again.',
  upload_no_usable_rows:
    'Upload has no usable required identifiers. Check the multi-value delimiter and required columns, then try again.',
  upload_rows_rejected:
    'Some rows failed the selected email or phone format. Clean those rows in the table and upload again.',
  upload_invalid_format: 'The email or phone format setting is not supported.',
  upload_invalid_delimiter: 'The multi-value delimiter is not supported. Choose None, ;, |, or ,.',
}

/** Human label for a connection system id — Axios HQ for `axios_hq` and retracted alias. */
export function connectionSystemDisplayLabel(
  system: string | null | undefined,
  fallback?: string | null,
): string {
  const catalogId = catalogDisplaySystemId(system)
  if (catalogId === AXIOS_HQ_CATALOG_SYSTEM_ID) return 'Axios HQ'
  if (catalogId in CONNECT_SYSTEM_LABELS) {
    return CONNECT_SYSTEM_LABELS[catalogId as IntegrationSystemId]
  }
  if (catalogId) return catalogId.replaceAll('_', ' ')
  const named = (fallback ?? '').trim()
  return named || 'Unknown'
}

/** Human label for loading/success copy — prefers system id, falls back to display name. */
export function connectRedeemSystemLabel(
  preview: Pick<ConnectPreviewPayload, 'system' | 'display_name'>,
): string {
  return connectionSystemDisplayLabel(preview.system, preview.display_name)
}

/** Owner-safe success toast description from allowlisted redeem `detail`. */
export function connectTestSuccessDescription(
  detail: string | null | undefined,
  displayName: string,
): string {
  const code = detail?.trim().toLowerCase()
  if (code && CONNECT_TEST_SUCCESS_DESCRIPTIONS[code]) {
    return CONNECT_TEST_SUCCESS_DESCRIPTIONS[code]
  }
  return `Your ${displayName} connection test completed successfully.`
}

/** Owner-safe failure message from allowlisted redeem/test `detail`. */
export function connectTestFailureMessage(detail: string | null | undefined): string {
  const code = detail?.trim().toLowerCase()
  if (code && CONNECT_TEST_FAILURE_MESSAGES[code]) {
    return CONNECT_TEST_FAILURE_MESSAGES[code]
  }
  return 'Connection test failed. Ask your Habeas contact to send a new invite.'
}

export function listConnections() {
  return fetchAdminApi<{ connections: ConnectionRecord[] }>('/ops/connections', {
    timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS,
  })
}

/** Create a connection. Axios HQ writes use `axios_hq` — `axios_headquarters` is retracted. */
export function createConnection(body: {
  system: IntegrationSystemId
  display_name: string
  owner_email?: string | null
}) {
  return fetchAdminApi<ConnectionRecord>('/ops/connections', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function createConnectionInvite(
  connectionId: string,
  body?: { owner_email?: string },
) {
  // Always send JSON `{}` — FastAPI requires a body for InviteCreateBody;
  // omitting it yields 422 "Field required" / loc ["body"].
  return fetchAdminApi<ConnectionInviteCreateResponse>(
    `/ops/connections/${encodeURIComponent(connectionId)}/invites`,
    {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    },
  )
}

export function revokeConnectionInvite(connectionId: string, inviteId: string) {
  return fetchAdminApi<{ status: string }>(
    `/ops/connections/${encodeURIComponent(connectionId)}/invites/${encodeURIComponent(inviteId)}/revoke`,
    { method: 'POST' },
  )
}

export function deleteConnection(connectionId: string) {
  return fetchAdminApi<{ status: string; connection_id: string }>(
    `/ops/connections/${encodeURIComponent(connectionId)}`,
    { method: 'DELETE' },
  )
}

export function testConnection(connectionId: string) {
  return fetchAdminApi<{ ok: boolean; detail: string | null }>(
    `/ops/connections/${encodeURIComponent(connectionId)}/test`,
    { method: 'POST' },
  )
}

export function getConnectionSystems() {
  return fetchAdminApi<ConnectionSystemsPayload>('/ops/connections/systems')
}

export type ConnectionOwnerCandidate = {
  email: string
  role: string
}

export function listConnectionOwnerCandidates() {
  return fetchAdminApi<{ owners: ConnectionOwnerCandidate[] }>(
    '/ops/connections/owner-candidates',
  )
}

export function forceConnectionMode(
  connectionId: string,
  body: { mode: 'live' | 'upload'; reason?: string | null },
) {
  return fetchAdminApi<ConnectionRecord>(
    `/ops/connections/${encodeURIComponent(connectionId)}/mode`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

export function overrideConnectionCadence(
  connectionId: string,
  body: { cadence_days_override: number | null },
) {
  return fetchAdminApi<ConnectionRecord>(
    `/ops/connections/${encodeURIComponent(connectionId)}/cadence`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

export function resetConnectionWizard(connectionId: string) {
  return fetchAdminApi<ConnectionRecord>(
    `/ops/connections/${encodeURIComponent(connectionId)}/wizard/reset`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export type VerticalCatalogEntry = {
  id: string
  display_label: string
  view_only: boolean
  sort_order: number
}

export type VerticalAssignment = {
  email: string
  vertical_id: string
  active: boolean
  added_at?: string | null
  added_by?: string | null
}

export type VerticalBinding = {
  vertical_id: string
  system: string
  allowed_approaches: string[]
  active?: boolean
}

export function listVerticalCatalog() {
  return fetchAdminApi<VerticalCatalogEntry[]>('/ops/verticals')
}

export function listVerticalAssignments() {
  return fetchAdminApi<VerticalAssignment[]>('/ops/verticals/assignments')
}

export function addVerticalAssignment(body: { email: string; vertical_id: string }) {
  return fetchAdminApi<VerticalAssignment>('/ops/verticals/assignments', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function removeVerticalAssignment(verticalId: string, email: string) {
  return fetchAdminApi<void>(
    `/ops/verticals/assignments/${encodeURIComponent(verticalId)}/${encodeURIComponent(email)}`,
    { method: 'DELETE' },
  )
}

export function listVerticalBindings(verticalId: string) {
  return fetchAdminApi<VerticalBinding[]>(
    `/ops/verticals/${encodeURIComponent(verticalId)}/bindings`,
  )
}

export type VerticalMember = {
  email: string
  vertical_id: string
  assignment_role: 'data_owner' | 'data_user' | string
  active: boolean
}

export type MemberInvite = {
  invite_id: string
  vertical_id: string
  expires_at: string
  invite_url: string
  raw_token: string
}

export type MemberInvitePreview = {
  kind: 'data_user' | string
  vertical_id: string
  vertical_label: string
  role: string
  expires_at?: string | null
}

export function listVerticalMembers(verticalId: string) {
  return fetchAdminApi<VerticalMember[]>(
    `/owner/verticals/${encodeURIComponent(verticalId)}/members`,
  )
}

export function mintVerticalMemberInvite(verticalId: string, email: string) {
  return fetchAdminApi<MemberInvite>(
    `/owner/verticals/${encodeURIComponent(verticalId)}/member-invites`,
    {
      method: 'POST',
      body: JSON.stringify({ email }),
    },
  )
}

export function getConnectInvitePreview(token: string) {
  return fetchAdminApi<MemberInvitePreview>(`/connect/${encodeURIComponent(token)}`)
}

export function redeemConnectInvite(token: string) {
  return fetchAdminApi<MemberInvitePreview>(`/connect/${encodeURIComponent(token)}`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export type OwnerConnectorSystem = {
  system: string
  display_name: string
  allowed_approaches: string[]
  connection_id: string | null
  connection_method?: string | null
  connection_method_label?: string | null
  upload_allowed?: boolean
  status: string | null
  last_test_ok: boolean | null
  metadata: Record<string, unknown>
  display_status: string
  gate_code: string
  gate_allowed: boolean
  // Surfaced by admin-api inside `metadata.wizard_completed_at`; top-level only
  // if ConnectorSystemOut grows the field. Prefer wizardCompletedAt(metadata)
  // from @/lib/quick-start-tour.
  wizard_completed_at?: string | null
}

export type OwnerConnectorList = {
  vertical_id: string
  display_label: string
  view_only: boolean
  connectors: OwnerConnectorSystem[]
}

export type OwnerRejectedUploadRow = {
  row: number
  codes: string[]
}

export type OwnerUploadResult = {
  ok: boolean
  detail: string
  connection_id: string
  upload_row_count?: number | null
  missing_count?: number | null
  detected_header_count?: number | null
  detected_headers?: string[] | null
  required_headers?: string[] | null
  accepted_row_count?: number | null
  rejected_row_count?: number | null
  rejected_rows?: OwnerRejectedUploadRow[] | null
}

export function listOwnerVisibleVerticals() {
  return fetchAdminApi<VerticalCatalogEntry[]>('/owner/verticals', {
    timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS,
  })
}

export function listOwnerConnectors(verticalId: string) {
  return fetchAdminApi<OwnerConnectorList>(
    `/owner/verticals/${encodeURIComponent(verticalId)}/connectors`,
    { timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS },
  )
}

export type OwnerVerticalSettings = {
  notify_email: boolean
  notify_slack: boolean
}

export function getOwnerVerticalSettings(
  verticalId: string,
): Promise<OwnerVerticalSettings> {
  return fetchAdminApi<OwnerVerticalSettings>(
    `/owner/verticals/${encodeURIComponent(verticalId)}/settings`,
    { timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS },
  )
}

export function patchOwnerVerticalSettings(
  verticalId: string,
  body: Partial<OwnerVerticalSettings>,
): Promise<OwnerVerticalSettings> {
  return fetchAdminApi<OwnerVerticalSettings>(
    `/owner/verticals/${encodeURIComponent(verticalId)}/settings`,
    { method: 'PATCH', body: JSON.stringify(body) },
  )
}

export function setOwnerConnectorMode(
  verticalId: string,
  system: string,
  body: { mode: 'live' | 'upload' },
) {
  return fetchAdminApi<OwnerConnectorSystem>(
    `/owner/verticals/${encodeURIComponent(verticalId)}/systems/${encodeURIComponent(system)}/mode`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

export type RefreshCadence = 'rarely' | 'with_new_batches' | 'weekly'
export type OwnerCadenceBody = {
  cadence_days?: number
  refresh_policy?: 'static' | 'volatile'
  refresh_cadence?: RefreshCadence
}

export function setOwnerConnectorCadence(
  verticalId: string,
  system: string,
  body: OwnerCadenceBody,
) {
  return fetchAdminApi<OwnerConnectorSystem>(
    `/owner/verticals/${encodeURIComponent(verticalId)}/systems/${encodeURIComponent(system)}/cadence`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

export function completeOwnerConnectorWizard(
  verticalId: string,
  system: string,
  body?: OwnerCadenceBody,
) {
  return fetchAdminApi<OwnerConnectorSystem>(
    `/owner/verticals/${encodeURIComponent(verticalId)}/systems/${encodeURIComponent(system)}/wizard/complete`,
    { method: 'POST', body: JSON.stringify(body ?? {}) },
  )
}

export type OwnerLiveConnectResult = {
  ok: boolean
  detail: string
  connection_id: string
}

export type OwnerCredentialPreview = {
  system: string
  display_name: string
  fields: Array<{
    id: string
    label: string
    input_type: 'password' | 'text' | 'url'
    required: boolean
    help: string | null
  }>
  trust_copy: string
  connection_method_label?: string | null
  upload_allowed?: boolean
}

/** Credential fields + how-to copy for in-wizard Live connect (KD21). */
export function getOwnerConnectorCredentialPreview(verticalId: string, system: string) {
  return fetchAdminApi<OwnerCredentialPreview>(
    `/owner/verticals/${encodeURIComponent(verticalId)}/systems/${encodeURIComponent(system)}/credential-preview`,
  )
}

/** In-wizard Live credentials submit + connection test (KTD15). */
export function saveOwnerConnectorCredentials(
  verticalId: string,
  system: string,
  credentials: Record<string, string>,
) {
  return fetchAdminApi<OwnerLiveConnectResult>(
    `/owner/verticals/${encodeURIComponent(verticalId)}/systems/${encodeURIComponent(system)}/credentials`,
    {
      method: 'POST',
      body: JSON.stringify({ credentials }),
    },
  )
}

/** Re-test stored Live credentials on the vertical-scoped row (retry without resubmit). */
export function testOwnerConnector(verticalId: string, system: string) {
  return fetchAdminApi<OwnerLiveConnectResult>(
    `/owner/verticals/${encodeURIComponent(verticalId)}/systems/${encodeURIComponent(system)}/test`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export async function uploadOwnerConnectorCsv(
  verticalId: string,
  system: string,
  file: File,
  multiPiiDelimiter: string | null,
  columnMapping?: Record<string, string> | null,
  formats?: {
    emailFormat?: string
    phoneFormat?: string
    nameFormat?: 'first_last' | 'last_first'
  },
): Promise<OwnerUploadResult> {
  await refreshAdminApiUserTokenIfNeeded()
  const headers = adminApiAuthHeaders({ Accept: 'application/json' })
  const form = new FormData()
  form.append('file', file)
  if (multiPiiDelimiter != null) {
    form.append('multi_pii_delimiter', multiPiiDelimiter)
  }
  if (columnMapping && Object.keys(columnMapping).length > 0) {
    form.append('column_mapping', JSON.stringify(columnMapping))
  }
  if (formats?.emailFormat) {
    form.append('email_format', formats.emailFormat)
  }
  if (formats?.phoneFormat) {
    form.append('phone_format', formats.phoneFormat)
  }
  if (formats?.nameFormat) {
    form.append('name_format', formats.nameFormat)
  }
  const response = await fetch(
    adminApiRequestUrl(
      `/owner/verticals/${encodeURIComponent(verticalId)}/systems/${encodeURIComponent(system)}/upload`,
    ),
    { method: 'POST', headers, body: form },
  )
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`Admin API ${response.status}: ${detail || response.statusText}`)
  }
  return (await response.json()) as OwnerUploadResult
}

export async function downloadOwnerUploadTemplate(
  verticalId: string,
  system: string,
): Promise<Blob> {
  await refreshAdminApiUserTokenIfNeeded()
  const headers = adminApiAuthHeaders()
  const response = await fetch(
    adminApiRequestUrl(
      `/owner/verticals/${encodeURIComponent(verticalId)}/systems/${encodeURIComponent(system)}/upload-template`,
    ),
    { headers },
  )
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`Admin API ${response.status}: ${detail || response.statusText}`)
  }
  return response.blob()
}

/* --- Owner Sheets OAuth (hr_alumni / bizdev_contacts live connect) -------- */

export type OwnerSheetsOauthStartBody = {
  redirect_uri: string
}

export type OwnerSheetsOauthStartResponse = {
  session_id: string
  authorize_url: string
  state: string
}

export type OwnerSheetsOauthRedeemBody = {
  session_id: string
  code: string
  state: string
}

export type OwnerSheetsOauthRedeemResponse = {
  ok: boolean
  detail: string
  connection_id?: string
  google_email_domain?: string | null
}

export type OwnerSheetsOauthTab = {
  title: string
  sheet_id?: number | null
}

export type OwnerSheetsOauthFile = {
  spreadsheet_id: string
  name: string
  tabs?: OwnerSheetsOauthTab[]
}

export type OwnerSheetsOauthFilesResponse = {
  files: OwnerSheetsOauthFile[]
}

export type OwnerSheetsOauthExtractBody = {
  spreadsheet_id: string
  tab: string
  multi_pii_delimiter?: string | null
  column_mapping?: Record<string, string> | null
  email_format?: string
  phone_format?: string
}

function ownerSheetsOauthPath(verticalId: string, system: string, action: string) {
  return `/owner/verticals/${encodeURIComponent(verticalId)}/systems/${encodeURIComponent(system)}/sheets-oauth/${action}`
}

export function ownerSheetsOauthStart(
  verticalId: string,
  system: string,
  body: OwnerSheetsOauthStartBody,
) {
  return fetchAdminApi<OwnerSheetsOauthStartResponse>(
    ownerSheetsOauthPath(verticalId, system, 'start'),
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  )
}

export function ownerSheetsOauthRedeem(
  verticalId: string,
  system: string,
  body: OwnerSheetsOauthRedeemBody,
) {
  return fetchAdminApi<OwnerSheetsOauthRedeemResponse>(
    ownerSheetsOauthPath(verticalId, system, 'redeem'),
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  )
}

export function ownerSheetsOauthFiles(verticalId: string, system: string) {
  return fetchAdminApi<OwnerSheetsOauthFilesResponse>(
    ownerSheetsOauthPath(verticalId, system, 'files'),
  )
}

export function ownerSheetsOauthExtract(
  verticalId: string,
  system: string,
  body: OwnerSheetsOauthExtractBody,
) {
  return fetchAdminApi<OwnerUploadResult>(ownerSheetsOauthPath(verticalId, system, 'extract'), {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function listOwnerConnectorReminders() {
  return fetchAdminApi<{ reminders: ConnectorReminder[] }>('/owner/connector-reminders', {
    timeoutMs: OPS_FAST_QUERY_TIMEOUT_MS,
  })
}

export function getConnectPreview(token: string) {
  return fetchAdminApi<ConnectPreviewPayload>(`/connect/${encodeURIComponent(token)}`)
}

export function redeemConnect(token: string, credentials: Record<string, string>) {
  return fetchAdminApi<ConnectRedeemResponse>(`/connect/${encodeURIComponent(token)}`, {
    method: 'POST',
    body: JSON.stringify({ credentials }),
  })
}

// ---------------------------------------------------------------------------
// Worker fleet discovery + attempt-table browser (E5 contract — additive)
// ---------------------------------------------------------------------------

export type FleetWorkerHealth = {
  ok: boolean
  status_code?: number | null
  ready?: { status?: string; service?: string }
  error?: string
}

export type FleetWorkerRecord = {
  /** Stable snake_case id — prefer over legacy `name`. */
  worker_key: string
  /** Legacy alias — some payloads still use `name`. */
  name?: string
  label?: string
  ok?: boolean
  status_code?: number | null
  ready?: { status?: string; service?: string }
  scheduled: boolean
  deployed: boolean
  service_name?: string | null
  base_url?: string | null
  sources?: ('scheduler' | 'cloud_run' | 'env')[]
  schedule_job_keys?: string[]
  attempt_table: string | null
  supports_unified_runs?: boolean
  health?: FleetWorkerHealth
  queue?: DropWorkerQueue
}

export type FleetWorkersPayload = {
  discovery_mode?: 'gcp' | 'local' | string
  discovery_warnings?: { code?: string; detail?: string }[]
  workers: FleetWorkerRecord[]
}

export type AttemptTableCatalogEntry = {
  table_name: string
  worker_key?: string | null
  worker_name?: string | null
  label?: string
  /** Allowlisted column ids — server advertises; never invent client-side. */
  columns?: string[]
  filterable_columns?: string[]
  sortable_columns?: string[]
}

export type AttemptTableCatalogPayload = {
  tables: AttemptTableCatalogEntry[]
}

export type AttemptTableRow = Record<string, string | number | boolean | null>

export type AttemptTableRowsPayload = {
  table_name: string
  columns: string[]
  rows: AttemptTableRow[]
  total?: number
  count?: number
  next_offset?: number | null
  next_cursor?: string | null
}

export type AttemptTableRowsQuery = {
  table_name: string
  status?: string
  request_id?: string
  step?: string
  window?: OpsTimeWindow
  since?: string
  limit?: number
  offset?: number
}

function mapDropWorkerToFleet(worker: DropWorkerRecord): FleetWorkerRecord {
  return {
    worker_key: worker.name,
    name: worker.name,
    label: worker.name,
    ok: worker.ok,
    status_code: worker.status_code,
    ready: worker.ready,
    scheduled: false,
    deployed: true,
    service_name: worker.ready?.service ?? null,
    base_url: null,
    sources: [],
    schedule_job_keys: [],
    attempt_table: worker.queue?.table ?? null,
    health: {
      ok: worker.ok,
      status_code: worker.status_code,
      ready: worker.ready,
    },
    queue: worker.queue,
  }
}

/** Prefer `GET /ops/workers/fleet`; fall back to drop workers when discovery is not deployed. */
export async function getFleetWorkers(): Promise<FleetWorkersPayload> {
  try {
    return await fetchAdminApi<FleetWorkersPayload>('/ops/workers/fleet')
  } catch (error) {
    const missing =
      error instanceof Error && /Admin API (404|501)/.test(error.message)
    if (!missing) throw error
    const drop = await getDropWorkers()
    return {
      discovery_mode: 'drop_workers_fallback',
      discovery_warnings: [
        {
          code: 'fleet_endpoint_unavailable',
          detail: 'Fell back to GET /ops/drop/workers',
        },
      ],
      workers: drop.workers.map(mapDropWorkerToFleet),
    }
  }
}

export function getAttemptTableCatalog(): Promise<AttemptTableCatalogPayload> {
  return fetchAdminApi<AttemptTableCatalogPayload>('/ops/workers/attempt-tables')
}

export function getAttemptTableRows(
  query: AttemptTableRowsQuery,
): Promise<AttemptTableRowsPayload> {
  const params = new URLSearchParams()
  if (query.status) params.set('status', query.status)
  if (query.request_id) params.set('request_id', query.request_id)
  if (query.step) params.set('step', query.step)
  if (query.window && query.window !== 'custom') params.set('window', query.window)
  if (query.since) params.set('since', query.since)
  if (query.limit != null) params.set('limit', String(query.limit))
  if (query.offset != null) params.set('offset', String(query.offset))
  const qs = params.toString()
  return fetchAdminApi<AttemptTableRowsPayload>(
    `/ops/workers/attempt-tables/${encodeURIComponent(query.table_name)}/rows${
      qs ? `?${qs}` : ''
    }`,
  )
}

/* --- Dev lab: Sheets owner OAuth ----------------------------------------- */

export type SheetsOauthLabStatus = {
  configured: boolean
  actor_email: string
  scopes: string[]
  allowed_redirect_uris: string[]
  secret_store: string
  note: string
}

export type SheetsOauthLabStartResponse = {
  lab_session_id: string
  authorize_url: string
  state: string
}

export type SheetsOauthLabRedeemResponse = {
  ok: boolean
  detail: string
  google_email_domain: string | null
  spreadsheet_id: string | null
}

export type SheetsOauthLabTestResponse = {
  ok: boolean
  detail: string
  spreadsheet_id: string | null
  sheet_count: number | null
  step: string
}

export function getSheetsOauthLabStatus() {
  return fetchAdminApi<SheetsOauthLabStatus>('/ops/lab/sheets-oauth/status')
}

export function sheetsOauthLabStart(body: {
  spreadsheet_url: string
  redirect_uri: string
}) {
  return fetchAdminApi<SheetsOauthLabStartResponse>('/ops/lab/sheets-oauth/start', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function sheetsOauthLabRedeem(body: {
  lab_session_id: string
  code: string
  state: string
}) {
  return fetchAdminApi<SheetsOauthLabRedeemResponse>('/ops/lab/sheets-oauth/redeem', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function sheetsOauthLabTest(body: { lab_session_id: string }) {
  return fetchAdminApi<SheetsOauthLabTestResponse>('/ops/lab/sheets-oauth/test', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/* --- Dev lab: prod DROP cutover (impl-04 /ops/drop/prod/*) --------------- */

export type DropProdApiKeySaveResult = {
  status: string
  configured: boolean
}

export type DropProdConfirmRunResult = {
  status: string
  process_id?: number | null
  run_id?: string | null
}

export type DropProdRunStatus = {
  status: string
  configured?: boolean
  process_id?: number | null
  run_id?: string | null
}

/** Store prod X-API-KEY. Response never includes the key. */
export function saveDropProdApiKey(body: { api_key: string }) {
  return fetchAdminApi<DropProdApiKeySaveResult>('/ops/drop/prod/key', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** Confirm download → land → promote → dispatch → Data ensure-drain. */
export function confirmDropProdRun(body: { confirm: true }) {
  return fetchAdminApi<DropProdConfirmRunResult>('/ops/drop/prod/confirm-run', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getDropProdRunStatus() {
  return fetchAdminApi<DropProdRunStatus>('/ops/drop/prod/status')
}

/* --- Auth0 match search / confirm (S09 APIs; design lab later) ----------- */

export type Auth0MatchCandidate = {
  vendor_record_id: string
}

export type Auth0MatchCandidatesResponse = {
  match_count: number
  candidates: Auth0MatchCandidate[]
}

export type Auth0MatchCandidatesStatus = {
  snapshot_present: boolean
  match_count: number
}

export type Auth0DispositionBody = {
  status: DropResponseStatusCode
  vendor_record_ids?: string[]
  decision_reason?: string | null
}

export type Auth0Disposition = {
  request_id: string
  vertical: string
  label: string
  live: boolean
  status: number
  selected_dwids: string[]
  selected_dwid_count: number
  selected_vendor_record_ids: string[]
  selected_vendor_record_id_count: number
  decided_by: string
  actor_role: string | null
  decided_at: string
  updated_at: string | null
}

export function getAuth0MatchCandidates(requestId: string) {
  return fetchAdminApi<Auth0MatchCandidatesResponse>(
    `/requests/${encodeURIComponent(requestId)}/verticals/auth0/match-candidates`,
  )
}

export function getAuth0MatchCandidatesStatus(requestId: string) {
  return fetchAdminApi<Auth0MatchCandidatesStatus>(
    `/requests/${encodeURIComponent(requestId)}/verticals/auth0/match-candidates/status`,
  )
}

export function putAuth0Disposition(requestId: string, body: Auth0DispositionBody) {
  return fetchAdminApi<Auth0Disposition>(
    `/requests/${encodeURIComponent(requestId)}/dispositions/auth0`,
    {
      method: 'PUT',
      body: JSON.stringify(body),
    },
  )
}
