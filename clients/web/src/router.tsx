import { createRootRoute, createRoute, createRouter, Outlet, redirect } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/router-devtools'

import { AppShell } from '@/components/AppShell'
import { DashboardPage } from '@/routes/index'
import { OpsDashboardPage } from '@/routes/ops/dashboard'
import { DeMonitorPage } from '@/routes/ops/de-monitor'
import { OpsIncidentsPage } from '@/routes/ops/incidents'
import { OpsJobsPage } from '@/routes/ops/jobs'
import { OpsRunsPage } from '@/routes/ops/runs'
import { RunDetailPage } from '@/routes/ops/run-detail'
import { WorkersPage, WorkersTrendsPage } from '@/routes/ops/workers'
import { WorkersSettingsPage } from '@/routes/ops/workers/settings'
import { HealthConfigurationPage } from '@/routes/ops/health/configuration'
import { HealthEscalationsPage } from '@/routes/ops/health/escalations'
import { HealthLandingPage } from '@/routes/ops/health/index'
import { RequestDetailPage } from '@/routes/requests/$requestId'
import { NeedsAttentionPage } from '@/routes/requests/needs-attention'
import { ConditionsPage } from '@/routes/requests/conditions'
import { ManualRequestPage } from '@/routes/requests/new'
import { RequestsPage } from '@/routes/requests/index'
import { RequestsSlasPage } from '@/routes/requests/slas'
import { DocsPage } from '@/routes/docs'
import { HOME_WINDOWS, type HomeWindow } from '@/components/legal/home/DateToolbar'

export const PIPELINE_TABS = [
  'pipeline',
  'hash_refresh',
  'history',
  'configurations',
] as const

export type PipelineTab = (typeof PIPELINE_TABS)[number]

/** Stage tabs live inside each bulk-run card (not the top console bar). */
export const PIPELINE_STAGE_TABS = [
  'download',
  'ingest',
  'matching',
  'review',
  'fulfillment',
] as const

export type PipelineStageTab = (typeof PIPELINE_STAGE_TABS)[number]

export type PipelineSearch = {
  tab: PipelineTab
  process?: number
  stage?: PipelineStageTab
}

export type IndexSearch = PipelineSearch & {
  /** Legal Home analytics window — not used by DROP pipeline console. */
  home_window?: HomeWindow
}

function parsePipelineTab(value: unknown): PipelineTab {
  if (typeof value === 'string' && PIPELINE_TABS.includes(value as PipelineTab)) {
    return value as PipelineTab
  }
  // Legacy deep links: Home and stage tabs → Pipeline
  if (
    value === 'home' ||
    (typeof value === 'string' &&
      PIPELINE_STAGE_TABS.includes(value as PipelineStageTab))
  ) {
    return 'pipeline'
  }
  return 'pipeline'
}

function parsePipelineStage(
  value: unknown,
  tabRaw: unknown,
): PipelineStageTab | undefined {
  if (
    typeof value === 'string' &&
    PIPELINE_STAGE_TABS.includes(value as PipelineStageTab)
  ) {
    return value as PipelineStageTab
  }
  if (
    typeof tabRaw === 'string' &&
    PIPELINE_STAGE_TABS.includes(tabRaw as PipelineStageTab)
  ) {
    return tabRaw as PipelineStageTab
  }
  return undefined
}

function parseProcessId(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value) && value >= 1) {
    return Math.floor(value)
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number.parseInt(value.trim(), 10)
    if (Number.isFinite(parsed) && parsed >= 1) return parsed
  }
  return undefined
}

function parsePipelineSearch(search: Record<string, unknown>): PipelineSearch {
  const parsed: PipelineSearch = {
    tab: parsePipelineTab(search.tab),
  }
  const process = parseProcessId(search.process)
  if (process != null) parsed.process = process
  const stage = parsePipelineStage(search.stage, search.tab)
  if (stage != null) parsed.stage = stage
  return parsed
}

function parseIndexSearch(search: Record<string, unknown>): IndexSearch {
  const parsed: IndexSearch = parsePipelineSearch(search)
  if (
    typeof search.home_window === 'string' &&
    HOME_WINDOWS.includes(search.home_window as HomeWindow)
  ) {
    parsed.home_window = search.home_window as HomeWindow
  }
  return parsed
}

export const RUNS_WINDOWS = ['8h', '24h', '1w', '3m', 'custom'] as const
export type RunsWindow = (typeof RUNS_WINDOWS)[number]

export const RUNS_STATUS_FILTERS = [
  'failed',
  'success',
  'claimed',
  'in_flight',
  'pending',
  'abandoned',
] as const
export type RunsStatusFilter = (typeof RUNS_STATUS_FILTERS)[number]

export const RUNS_JOB_FILTERS = [
  'drop_connector',
  'drop_ingestor',
  'matching',
  'hash_index_refresh',
] as const
export type RunsJobFilter = (typeof RUNS_JOB_FILTERS)[number]

export type RunsSearch = {
  window?: RunsWindow
  status?: RunsStatusFilter
  job?: RunsJobFilter
  request_id?: string
  /** Bulk process id (`drop_connector_attempts.id` download) — URL param `process`. */
  process?: number
  /** ISO timestamp — used when `window` is `custom`. */
  since?: string
}

export const DEFAULT_RUNS_WINDOW: RunsWindow = '1w'

export type BulkStageRunState =
  | 'queued'
  | 'in_flight'
  | 'failed'
  | 'abandoned'
  | 'finished'

/** Map a fleet worker name onto `/ops/runs` search (unified jobs only). */
export function runsSearchForWorker(
  workerName: string,
  extras?: Partial<RunsSearch>,
): RunsSearch {
  const next: RunsSearch = {
    window: DEFAULT_RUNS_WINDOW,
    ...extras,
  }
  if (RUNS_JOB_FILTERS.includes(workerName as RunsJobFilter)) {
    next.job = workerName as RunsJobFilter
  }
  return next
}

const BULK_STAGE_TO_RUNS_JOB: Record<PipelineStageTab, RunsJobFilter> = {
  download: 'drop_connector',
  ingest: 'drop_ingestor',
  matching: 'matching',
  // Review gates live on requests; closest unified job is matching.
  review: 'matching',
  // Fulfillment is response_status on requests; closest unified job is matching.
  fulfillment: 'matching',
}

const BULK_STATE_TO_RUNS_STATUS: Record<BulkStageRunState, RunsStatusFilter> = {
  queued: 'pending',
  in_flight: 'in_flight',
  failed: 'failed',
  abandoned: 'abandoned',
  finished: 'success',
}

/**
 * `/ops/runs` search for a bulk-card stage state tile.
 * Pass `process` (bulk download attempt id) so Runs scopes to that process.
 */
export function runsSearchForBulkStage(
  stageTab: PipelineStageTab,
  state: BulkStageRunState,
  extras?: Partial<RunsSearch>,
): RunsSearch {
  return {
    window: DEFAULT_RUNS_WINDOW,
    job: BULK_STAGE_TO_RUNS_JOB[stageTab],
    status: BULK_STATE_TO_RUNS_STATUS[state],
    ...extras,
  }
}

function parseRunsWindow(value: unknown): RunsWindow | undefined {
  if (typeof value === 'string' && (RUNS_WINDOWS as readonly string[]).includes(value)) {
    return value as RunsWindow
  }
  return undefined
}

function parseRunsSince(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  if (!trimmed) return undefined
  const parsed = Date.parse(trimmed)
  if (Number.isNaN(parsed)) return undefined
  return new Date(parsed).toISOString()
}

function parseRunsStatus(value: unknown): RunsStatusFilter | undefined {
  if (typeof value === 'string' && RUNS_STATUS_FILTERS.includes(value as RunsStatusFilter)) {
    return value as RunsStatusFilter
  }
  return undefined
}

function parseRunsJob(value: unknown): RunsJobFilter | undefined {
  if (typeof value === 'string' && RUNS_JOB_FILTERS.includes(value as RunsJobFilter)) {
    return value as RunsJobFilter
  }
  return undefined
}

function parseRunsRequestId(value: unknown): string | undefined {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (trimmed) return trimmed
  }
  return undefined
}

function parseRunsSearch(search: Record<string, unknown>): RunsSearch {
  const parsed: RunsSearch = {}
  const window = parseRunsWindow(search.window)
  if (window) parsed.window = window
  const status = parseRunsStatus(search.status)
  if (status) parsed.status = status
  const job = parseRunsJob(search.job)
  if (job) parsed.job = job
  const requestId = parseRunsRequestId(search.request_id)
  if (requestId) parsed.request_id = requestId
  const process = parseProcessId(search.process)
  if (process != null) parsed.process = process
  const since = parseRunsSince(search.since)
  if (since) parsed.since = since
  return parsed
}

/** Workers overview — URL filters only. */
export const WORKERS_WINDOWS = ['8h', '1w', '3m', 'custom'] as const
export type WorkersWindow = (typeof WORKERS_WINDOWS)[number]

export const WORKERS_TABS = ['failed', 'in_flight', 'waiting', 'all'] as const
export type WorkersStatusTab = (typeof WORKERS_TABS)[number]

export type WorkersSearch = {
  window?: WorkersWindow
  since?: string
  tab?: WorkersStatusTab
  job?: string
}

export type WorkersFailedSearch = {
  window?: WorkersWindow
  since?: string
}

function parseWorkersWindow(value: unknown): WorkersWindow | undefined {
  if (typeof value === 'string' && WORKERS_WINDOWS.includes(value as WorkersWindow)) {
    return value as WorkersWindow
  }
  return undefined
}

function parseWorkersSearch(search: Record<string, unknown>): WorkersSearch {
  const parsed: WorkersSearch = {}
  const window = parseWorkersWindow(search.window)
  if (window) parsed.window = window
  if (
    typeof search.tab === 'string' &&
    WORKERS_TABS.includes(search.tab as WorkersStatusTab)
  ) {
    parsed.tab = search.tab as WorkersStatusTab
  }
  if (typeof search.job === 'string' && search.job.trim()) {
    parsed.job = search.job.trim()
  }
  if (typeof search.since === 'string' && search.since.trim()) {
    parsed.since = search.since.trim()
  }
  return parsed
}

/** @deprecated Use WorkersSearch — kept for /ops/de-monitor redirect. */
export const DE_MONITOR_TABS = WORKERS_TABS
export type DeMonitorStatusTab = WorkersStatusTab

export type DeMonitorSearch = {
  window?: RunsWindow
  tab?: DeMonitorStatusTab
  job?: string
}

function parseDeMonitorSearch(search: Record<string, unknown>): DeMonitorSearch {
  const parsed: DeMonitorSearch = {}
  const window = parseRunsWindow(search.window)
  if (window) parsed.window = window
  if (
    typeof search.tab === 'string' &&
    DE_MONITOR_TABS.includes(search.tab as DeMonitorStatusTab)
  ) {
    parsed.tab = search.tab as DeMonitorStatusTab
  }
  if (typeof search.job === 'string' && search.job.trim()) {
    parsed.job = search.job.trim()
  }
  return parsed
}

function deMonitorToWorkersSearch(search: DeMonitorSearch): WorkersSearch {
  const mappedWindow: WorkersWindow | undefined =
    search.window === '24h' ? '1w' : search.window === '8h' ? '8h' : search.window === '1w' ? '1w' : undefined
  return {
    window: mappedWindow,
    tab: search.tab,
    job: search.job,
  }
}

const rootRoute = createRootRoute({
  component: () => (
    <AppShell>
      <Outlet />
      {import.meta.env.DEV ? <TanStackRouterDevtools position="bottom-right" /> : null}
    </AppShell>
  ),
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  validateSearch: (search: Record<string, unknown>) => parseIndexSearch(search),
  component: DashboardPage,
})

export const REQUESTS_DUE_FILTERS = ['overdue', 'due_soon', 'on_track'] as const
export type RequestsDueFilter = (typeof REQUESTS_DUE_FILTERS)[number]

export type RequestsSearch = {
  source?: 'webform' | 'drop' | 'csv' | 'manual'
  source_bucket?: 'drop' | 'other'
  request_type?: string
  stage?: string
  posture?: 'in_queue' | 'in_progress' | 'complete'
  state?: string
  attention?: 'needs' | 'clear'
  due?: RequestsDueFilter
  raw?: 'yes' | 'no'
  received_after?: string
  received_before?: string
}

function parseRequestsSearch(search: Record<string, unknown>): RequestsSearch {
  const parsed: RequestsSearch = {}
  if (
    typeof search.source === 'string' &&
    ['webform', 'drop', 'csv', 'manual'].includes(search.source)
  ) {
    parsed.source = search.source as RequestsSearch['source']
  }
  if (search.source_bucket === 'drop' || search.source_bucket === 'other') {
    parsed.source_bucket = search.source_bucket
  }
  if (typeof search.request_type === 'string' && search.request_type.trim()) {
    parsed.request_type = search.request_type.trim()
  }
  if (typeof search.stage === 'string' && search.stage.trim()) {
    parsed.stage = search.stage.trim()
  }
  if (
    search.posture === 'in_queue' ||
    search.posture === 'in_progress' ||
    search.posture === 'complete'
  ) {
    parsed.posture = search.posture
  }
  if (typeof search.state === 'string' && search.state.trim()) {
    parsed.state = search.state.trim().toUpperCase()
  }
  if (search.attention === 'needs' || search.attention === 'clear') {
    parsed.attention = search.attention
  }
  if (
    typeof search.due === 'string' &&
    REQUESTS_DUE_FILTERS.includes(search.due as RequestsDueFilter)
  ) {
    parsed.due = search.due as RequestsDueFilter
  }
  if (search.raw === 'yes' || search.raw === 'no') {
    parsed.raw = search.raw
  }
  if (typeof search.received_after === 'string' && search.received_after.trim()) {
    parsed.received_after = search.received_after.trim()
  }
  if (typeof search.received_before === 'string' && search.received_before.trim()) {
    parsed.received_before = search.received_before.trim()
  }
  return parsed
}

const requestsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/requests',
  validateSearch: (search: Record<string, unknown>) => parseRequestsSearch(search),
  component: RequestsPage,
})

export const NEEDS_ATTENTION_KINDS = [
  'all',
  'matching',
  'triage',
  'escalations',
  'delivery',
  'notice',
  'communications',
  'pending_tasks',
] as const

export type NeedsAttentionSearchKind = (typeof NEEDS_ATTENTION_KINDS)[number]

export const LEGAL_INBOX_FILTERS = [
  'unassigned',
  'assignment_to_legal',
  'fulfillment',
  'notice',
  'delivery',
  'pre_matching_holds',
  'assigned_to_me',
] as const

export type LegalInboxFilter = (typeof LEGAL_INBOX_FILTERS)[number]

export type NeedsAttentionSearch = {
  bulk?: number
  /** Inbox lane tab — Legal defaults to triage when omitted. */
  kind?: NeedsAttentionSearchKind
  /** Legal/admin filter chips (OQ14) — supersedes kind tabs when set. */
  filter?: LegalInboxFilter
  /** Scope matching review queue to a data-owner assignee (API `assignee` param). */
  assignee?: string
}

function parseNeedsAttentionSearch(search: Record<string, unknown>): NeedsAttentionSearch {
  const parsed: NeedsAttentionSearch = {}
  const raw = search.bulk
  const n =
    typeof raw === 'number'
      ? raw
      : typeof raw === 'string' && raw.trim()
        ? Number(raw)
        : NaN
  if (Number.isInteger(n) && n >= 1) parsed.bulk = n
  if (
    typeof search.kind === 'string' &&
    (NEEDS_ATTENTION_KINDS as readonly string[]).includes(search.kind)
  ) {
    parsed.kind = search.kind as NeedsAttentionSearchKind
  }
  if (
    typeof search.filter === 'string' &&
    (LEGAL_INBOX_FILTERS as readonly string[]).includes(search.filter)
  ) {
    parsed.filter = search.filter as LegalInboxFilter
  }
  if (typeof search.assignee === 'string' && search.assignee.trim()) {
    parsed.assignee = search.assignee.trim()
  }
  return parsed
}

const needsAttentionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/requests/needs-attention',
  validateSearch: (search: Record<string, unknown>) =>
    parseNeedsAttentionSearch(search),
  component: NeedsAttentionPage,
})

const requestsSlasRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/requests/slas',
  component: RequestsSlasPage,
})

const manualRequestRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/requests/new',
  component: ManualRequestPage,
})

const conditionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/requests/conditions',
  component: ConditionsPage,
})

const docsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/docs',
  component: DocsPage,
})

const requestDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/requests/$requestId',
  component: RequestDetailPage,
})

const matchingReviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/approvals/matching-review',
  beforeLoad: () => {
    throw redirect({ to: '/requests/needs-attention' })
  },
  component: () => null,
})

const opsDashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/dashboard',
  component: OpsDashboardPage,
})

const opsWorkersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/workers',
  validateSearch: (search: Record<string, unknown>) => parseWorkersSearch(search),
  component: WorkersPage,
})

const opsWorkersFailedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/workers/failed',
  beforeLoad: () => {
    throw redirect({
      to: '/ops/runs',
      search: { status: 'failed', window: DEFAULT_RUNS_WINDOW },
    })
  },
  component: () => null,
})

const opsWorkersSettingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/workers/settings',
  component: WorkersSettingsPage,
})

const opsWorkersTrendsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/workers/trends',
  component: WorkersTrendsPage,
})

const opsWorkerDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/workers/$workerName',
  beforeLoad: ({ params }) => {
    throw redirect({
      to: '/ops/runs',
      search: runsSearchForWorker(params.workerName),
    })
  },
  component: () => null,
})

const opsDeMonitorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/de-monitor',
  validateSearch: (search: Record<string, unknown>) => parseDeMonitorSearch(search),
  beforeLoad: ({ search }) => {
    throw redirect({
      to: '/ops/workers',
      search: deMonitorToWorkersSearch(search as DeMonitorSearch),
    })
  },
  component: DeMonitorPage,
})

const opsRunsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/runs',
  validateSearch: (search: Record<string, unknown>) => parseRunsSearch(search),
  component: OpsRunsPage,
})

const opsJobsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/jobs',
  component: OpsJobsPage,
})

const opsIncidentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/incidents',
  component: OpsIncidentsPage,
})

const dropPipelineRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/drop-pipeline',
  validateSearch: (search: Record<string, unknown>) => parsePipelineSearch(search),
  beforeLoad: ({ search }) => {
    throw redirect({
      to: '/',
      search: {
        tab: search.tab,
        process: search.process,
        stage: search.stage,
      },
    })
  },
  component: () => null,
})

const healthRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/health',
  component: HealthLandingPage,
})

const healthEscalationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/health/escalations',
  component: HealthEscalationsPage,
})

const healthConfigurationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/health/configuration',
  component: HealthConfigurationPage,
})

const runDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/runs/$job/$attemptId',
  component: RunDetailPage,
})

const routeTree = rootRoute.addChildren([
  indexRoute,
  requestsRoute,
  needsAttentionRoute,
  requestsSlasRoute,
  manualRequestRoute,
  conditionsRoute,
  docsRoute,
  requestDetailRoute,
  matchingReviewRoute,
  opsDashboardRoute,
  opsWorkersRoute,
  opsWorkersFailedRoute,
  opsWorkersSettingsRoute,
  opsWorkersTrendsRoute,
  opsWorkerDetailRoute,
  opsDeMonitorRoute,
  opsRunsRoute,
  opsJobsRoute,
  opsIncidentsRoute,
  dropPipelineRoute,
  healthRoute,
  healthEscalationsRoute,
  healthConfigurationRoute,
  runDetailRoute,
])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
