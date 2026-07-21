// Empty string (Cloud Run same-origin front door) must fall back to /api — not ??.
const API_BASE = import.meta.env.VITE_ADMIN_API_URL || '/api'

export type UserRole = 'super_admin' | 'admin' | 'data_owner'

export type MePayload = {
  email: string
  role: UserRole
}

export async function fetchAdminApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
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

export function getMe() {
  return fetchAdminApi<MePayload>('/me')
}

export function getHealth() {
  // Prefer /readyz: Cloud Run's public edge returns a Google HTML 404 for /healthz.
  return fetchAdminApi<HealthPayload>('/readyz')
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
  status: string
  request_id: string | null
  attempt_number?: number | null
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  error_code?: string | null
  error_message?: string | null
  timeline: RunTimelineStep[]
  events: RunEvent[]
}

/** Deployed /ops/runs job query literals ↔ UI / local worker names. */
const RUN_JOB_TO_API: Record<string, string> = {
  drop_connector: 'connector',
  connector: 'connector',
  drop_ingestor: 'ingest',
  drop_ingest: 'ingest',
  ingest: 'ingest',
  matching: 'matching',
  hash_index_refresh: 'hash_index',
  hash_index: 'hash_index',
}

const RUN_JOB_FROM_API: Record<string, string> = {
  connector: 'drop_connector',
  ingest: 'drop_ingestor',
  matching: 'matching',
  hash_index: 'hash_index_refresh',
}

function toApiRunJob(job: string | undefined): string | undefined {
  if (!job) return undefined
  return RUN_JOB_TO_API[job] ?? job
}

function fromApiRunJob(job: string): string {
  return RUN_JOB_FROM_API[job] ?? job
}

export async function getRunDetail(job: string, attemptId: number) {
  // Deployed admin-api: /ops/runs/{job}/{id}. Legacy encoded "job:id" 404s remotely.
  const apiJob = toApiRunJob(job) ?? job
  const raw = await fetchAdminApi<Record<string, unknown>>(
    `/ops/runs/${encodeURIComponent(apiJob)}/${encodeURIComponent(String(attemptId))}`,
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

function normalizeRunDetail(raw: Record<string, unknown>): RunDetail {
  const summary = normalizeRunSummary(raw)
  const timelineRaw = Array.isArray(raw.timeline) ? raw.timeline : []
  const eventsRaw = Array.isArray(raw.events) ? raw.events : []
  return {
    ...summary,
    attempt_id: summary.attempt_number,
    error_code: (raw.error_code as string | null | undefined) ?? null,
    error_message:
      (raw.error_message as string | null | undefined) ??
      (raw.error_redacted as string | null | undefined) ??
      null,
    timeline: timelineRaw.map((step, index) => {
      const row = step as Record<string, unknown>
      const key = String(row.key ?? row.event ?? row.step ?? `step-${index}`)
      return {
        key,
        label: String(row.label ?? row.event ?? row.step ?? key),
        status: normalizeTimelineStatus(row.status ?? 'completed'),
        timestamp: (row.timestamp as string | null | undefined) ?? (row.at as string | null | undefined) ?? null,
        detail: (row.detail as string | null | undefined) ?? null,
      }
    }),
    events: eventsRaw.map((event, index) => {
      const row = event as Record<string, unknown>
      return {
        id: String(row.id ?? `event-${index}`),
        event_type: String(row.event_type ?? row.kind ?? row.event ?? 'event'),
        occurred_at: String(row.occurred_at ?? row.at ?? ''),
        summary: (row.summary as string | null | undefined) ?? (row.detail as string | null | undefined) ?? null,
      }
    }),
  }
}

export async function listRuns(params?: {
  job?: string
  status?: string
  request_id?: string
  window?: OpsTimeWindow
  since?: string
  limit?: number
  offset?: number
}) {
  const search = new URLSearchParams()
  const apiJob = toApiRunJob(params?.job)
  if (apiJob) search.set('job', apiJob)
  if (params?.status) search.set('status', params.status)
  if (params?.request_id) search.set('request_id', params.request_id)
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
}

export type NeedsAttentionItem = {
  request_id: string
  reason: string
  current_stage: string
  intake_source: string
  received_at: string | null
  requested_at: string | null
}

export type NeedsAttentionResponse = {
  items: NeedsAttentionItem[]
}

export function getRequestJourney(requestId: string) {
  return fetchAdminApi<RequestJourneyResponse>(
    `/ops/requests/${encodeURIComponent(requestId)}/journey`,
  )
}

export function getNeedsAttention(limit?: number) {
  const search = new URLSearchParams()
  if (limit != null) search.set('limit', String(limit))
  const query = search.toString()
  return fetchAdminApi<NeedsAttentionResponse>(
    `/ops/requests/needs-attention${query ? `?${query}` : ''}`,
  )
}
