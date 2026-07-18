const API_BASE = import.meta.env.VITE_ADMIN_API_URL ?? '/api'
const API_IS_ABSOLUTE = /^https?:\/\//i.test(API_BASE)

export async function fetchAdminApi<T>(path: string, init?: RequestInit): Promise<T> {
  // Absolute admin-api hosts sit behind Identity-Aware Proxy — send cookies when present.
  // Local Vite uses same-origin `/api` (optionally injects IAP_ID_TOKEN via vite.config proxy).
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: init?.credentials ?? (API_IS_ABSOLUTE ? 'include' : 'same-origin'),
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
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

export function getHealth() {
  // Prefer /readyz: Cloud Run's public edge returns a Google HTML 404 for /healthz.
  return fetchAdminApi<HealthPayload>('/readyz')
}

export type AuthMePayload = {
  authenticated: boolean
  email: string | null
  actor: string
  iap_header_present: boolean
  service?: string
}

export function getAuthMe() {
  return fetchAdminApi<AuthMePayload>('/auth/me')
}

export function listRequests(intakeSource?: IntakeSource) {
  const query = intakeSource ? `?intake_source=${intakeSource}` : ''
  return fetchAdminApi<RequestRecord[]>(`/requests${query}`)
}

export function createManualRequest(body: ManualRequestInput) {
  return fetchAdminApi<RequestRecord>('/requests', {
    method: 'POST',
    body: JSON.stringify(body),
  })
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

export type MatchingResultDetail = MatchingResultRow & {
  attempt_id: number | null
  decided_by: string | null
  decided_at: string | null
  decision_reason: string | null
  attempts?: MatchingAttemptRow[]
  assignment?: WorkflowAssignmentSummary | null
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

/** Age-policy approaching counts (not legal DROP deadline / sla_monitor clocks). */
export type ApproachingSlaCounts = {
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

export type DropPipelineStatus = {
  connector_attempts: StepStatusCount[]
  ingest_attempts: StepStatusCount[]
  raw_requests_by_list_type: RawListTypeCount[]
  /** Absent on older admin-api revisions that predate fulfillment stage stats. */
  fulfillment?: DropFulfillmentStatus
  drop_requests: {
    count: number
    recent: DropRequestThin[]
  }
  matching_attempts: {
    pending: number
    success: number
    by_status: { status: string; count: number }[]
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
  /** Absent on older admin-api revisions that predate approaching-SLA aggregates. */
  approaching_sla?: ApproachingSlaCounts
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

export function postDropMatchingResultPromote(
  requestId: string,
  body?: { decision_reason?: string },
) {
  return fetchAdminApi<{ status: string; request_id: string; approval_id: number | null }>(
    `/ops/drop/matching-results/${requestId}/promote`,
    {
      method: 'POST',
      body: JSON.stringify({
        decided_by: 'web-admin@habeas.com',
        decision_reason: body?.decision_reason ?? 'promote to fulfillment',
      }),
    },
  )
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
