// Empty string (Cloud Run same-origin front door) must fall back to /api — not ??.
const API_BASE = import.meta.env.VITE_ADMIN_API_URL || '/api'

export type UserRole = 'super_admin' | 'admin' | 'legal' | 'data_owner'

/** sessionStorage key for X-Dev-Simulate-Role (super_admin local/dev only). */
export const SIMULATE_ROLE_STORAGE_KEY = 'habeas-cli.simulate-role'

export const SIMULATE_ROLE_VALUES: UserRole[] = [
  'super_admin',
  'admin',
  'legal',
  'data_owner',
]

export type MePayload = {
  email: string
  /** Effective role (after X-Dev-Simulate-Role when allowed). */
  role: UserRole
  /** Allowlist role before simulate override. */
  real_role: UserRole
}

export function getStoredSimulateRole(): UserRole | null {
  if (typeof sessionStorage === 'undefined') return null
  const value = sessionStorage.getItem(SIMULATE_ROLE_STORAGE_KEY)
  if (
    value === 'super_admin' ||
    value === 'admin' ||
    value === 'legal' ||
    value === 'data_owner'
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

export async function fetchAdminApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
  }
  const simulateRole = getStoredSimulateRole()
  if (simulateRole) {
    headers['X-Dev-Simulate-Role'] = simulateRole
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...headers,
      ...init?.headers,
    },
  })

  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`Admin API ${response.status}: ${detail || response.statusText}`)
  }

  return response.json() as Promise<T>
}

export type HealthPayload = {
  status: string
  service?: string
}

export type IntakeSource = 'webform' | 'drop' | 'csv' | 'manual'

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
  const me = await fetchAdminApi<MePayload>('/me')
  return {
    ...me,
    real_role: me.real_role ?? me.role,
  }
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

export function listRequests(options?: {
  intakeSource?: IntakeSource
  sourceBucket?: 'drop' | 'other'
  stage?: string
  posture?: 'in_queue' | 'in_progress' | 'complete'
  limit?: number
  q?: string
}) {
  const search = new URLSearchParams()
  if (options?.intakeSource) search.set('intake_source', options.intakeSource)
  if (options?.sourceBucket) search.set('source_bucket', options.sourceBucket)
  if (options?.stage) search.set('stage', options.stage)
  if (options?.posture) search.set('posture', options.posture)
  if (options?.limit != null) search.set('limit', String(options.limit))
  if (options?.q?.trim()) search.set('q', options.q.trim())
  const query = search.toString()
  return fetchAdminApi<RequestRecord[]>(`/requests${query ? `?${query}` : ''}`)
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
  const headers: Record<string, string> = { Accept: 'application/json' }
  const simulateRole = getStoredSimulateRole()
  if (simulateRole) {
    headers['X-Dev-Simulate-Role'] = simulateRole
  }
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${API_BASE}/requests/agent-batch`, {
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
  dob: string | null
  email: string | null
  phones: MatchedPersonPhone[]
}

export type MatchingResultDetail = MatchingResultRow & {
  attempt_id: number | null
  decided_by: string | null
  decided_at: string | null
  decision_reason: string | null
  attempts?: MatchingAttemptRow[]
  assignment?: WorkflowAssignmentSummary | null
  matched_contacts?: MatchedPersonContact[]
  matched_contacts_status?: 'ok' | 'none' | 'unavailable' | string
}

export type BulkApproveMatchingResultsInput = {
  match_type: MatchTypeFilter
  decided_by?: string
  decision_reason?: string
}

export type BulkApproveMatchingResultsResult = {
  status: string
  match_type: MatchTypeFilter
  ensured_count?: number
  approved_count: number
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
  interval_days?: number
}

export type WorkerSchedule = {
  job_key: string
  job_name: string
  label: string
  enabled: boolean
  schedule_kind: 'interval_days' | 'interval_minutes'
  interval_days: number | null
  interval_minutes: number | null
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
  table: string
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

export function getDropPipeline() {
  return fetchAdminApi<DropPipelineStatus>('/ops/drop/pipeline')
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
}

export type BulkProcessStageCounts = {
  total: number
  open: number
  success: number
  failed: number
  other?: number
  by_list_type?: { list_type: string | null; status: string; count: number }[]
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
  )
}

export function getDropBulkProcess(processId: number) {
  return fetchAdminApi<BulkProcessDetail>(`/ops/drop/processes/${processId}`)
}

export function listDropBulkProcessRuns(params: {
  stage: string
  day?: string
  days?: number
  process_id?: number
  status?: string
}) {
  const search = new URLSearchParams()
  search.set('stage', params.stage)
  if (params.day) search.set('day', params.day)
  if (params.days != null) search.set('days', String(params.days))
  if (params.process_id != null) search.set('process_id', String(params.process_id))
  if (params.status) search.set('status', params.status)
  return fetchAdminApi<BulkProcessRunsPayload>(
    `/ops/drop/processes/runs?${search.toString()}`,
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
  body?: { decision_reason?: string; response_status?: DropResponseStatusCode },
) {
  return fetchAdminApi<{
    status: string
    request_id: string
    approval_id: number | null
    response_status?: number
    response_status_set?: boolean
  }>(`/ops/drop/matching-results/${requestId}/promote`, {
    method: 'POST',
    body: JSON.stringify({
      decided_by: 'web-admin@habeas.com',
      decision_reason: body?.decision_reason ?? 'fulfill — matching review approved',
      ...(body?.response_status != null
        ? { response_status: body.response_status }
        : {}),
    }),
  })
}

export function postDropMatchingResultDecline(
  requestId: string,
  body?: { decision_reason?: string },
) {
  return fetchAdminApi<{ status: string; request_id: string; approval_id: number | null }>(
    `/ops/drop/matching-results/${requestId}/decline`,
    {
      method: 'POST',
      body: JSON.stringify({
        decided_by: 'web-admin@habeas.com',
        decision_reason: body?.decision_reason ?? 'decline — not fulfill-ready',
      }),
    },
  )
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
  matched_via?: string | null
  requestor_state?: string | null
  review_status?: string | null
  assignment?: NeedsAttentionAssignment | null
  /** drop_connector download attempt id — batch key for inbox threads */
  bulk_process_id?: number | null
  /** ZIP member name — fallback batch key when download ledger is missing */
  source_csv_filename?: string | null
}

export type NeedsAttentionResponse = {
  items: NeedsAttentionItem[]
  kind?: NeedsAttentionKind
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

export function getNeedsAttention(
  limitOrParams?:
    | number
    | { limit?: number; kind?: NeedsAttentionKind; assignee?: string },
) {
  const params =
    typeof limitOrParams === 'number'
      ? { limit: limitOrParams }
      : (limitOrParams ?? {})
  const search = new URLSearchParams()
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.kind) search.set('kind', params.kind)
  if (params.assignee) search.set('assignee', params.assignee)
  const query = search.toString()
  return fetchAdminApi<NeedsAttentionResponse>(
    `/ops/requests/needs-attention${query ? `?${query}` : ''}`,
  )
}

/** Legal case lanes only — excludes matching.review so ops volume cannot crowd Triage out. */
export const LEGAL_INBOX_KINDS: NeedsAttentionItemKind[] = [
  'triage',
  'escalations',
  'notice',
  'delivery',
]

export async function getLegalNeedsAttention(limit = 1000): Promise<NeedsAttentionResponse> {
  const results = await Promise.all(
    LEGAL_INBOX_KINDS.map((kind) => getNeedsAttention({ limit, kind })),
  )
  const items = results.flatMap((result) => result.items)
  items.sort((a, b) =>
    (a.requested_at || a.received_at || '').localeCompare(
      b.requested_at || b.received_at || '',
    ),
  )
  return { items, kind: 'all' }
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
  fulfillment_batches: Array<{
    batch_key: string
    source_label: string
    received_at: string
    request_count: number
  }>
  stage_reach_counts: Array<{
    stage: string
    reached_count: number
    dropped_count: number
  }>
  heatmap_cells: Array<{
    intake_source: string
    request_type: string
    count: number
  }>
  deadline_risk: {
    overdue: number
    due_within_7_days: number
    on_track: number
    closed_ytd: number
  }
  operations_pulse: {
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
