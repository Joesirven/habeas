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
import { WorkerDetailPage } from '@/routes/ops/workers/$workerName'
import { WorkersFailedPage } from '@/routes/ops/workers/failed'
import { WorkersSettingsPage } from '@/routes/ops/workers/settings'
import { HealthConfigurationPage } from '@/routes/ops/health/configuration'
import { HealthEscalationsPage } from '@/routes/ops/health/escalations'
import { HealthLandingPage } from '@/routes/ops/health/index'
import { RequestDetailPage } from '@/routes/requests/$requestId'
import { NeedsAttentionPage } from '@/routes/requests/needs-attention'
import { ManualRequestPage } from '@/routes/requests/new'
import { RequestsPage } from '@/routes/requests/index'
import { RequestsSlasPage } from '@/routes/requests/slas'

export const PIPELINE_TABS = [
  'home',
  'download',
  'ingest',
  'matching',
  'fulfillment',
  'hash_refresh',
  'history',
  'configurations',
] as const

export type PipelineTab = (typeof PIPELINE_TABS)[number]

function parsePipelineTab(value: unknown): PipelineTab {
  if (typeof value === 'string' && PIPELINE_TABS.includes(value as PipelineTab)) {
    return value as PipelineTab
  }
  return 'home'
}

/** Primary filter pills (legacy `24h` still parseable from URLs). */
export const RUNS_WINDOWS = ['8h', '1w', '3m', 'custom'] as const
export type RunsWindow = (typeof RUNS_WINDOWS)[number] | '24h'

export const RUNS_STATUS_FILTERS = ['failed', 'success', 'claimed', 'in_flight'] as const
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
}

export const DEFAULT_RUNS_WINDOW: RunsWindow = '1w'

function parseRunsWindow(value: unknown): RunsWindow | undefined {
  if (typeof value !== 'string') return undefined
  if ((RUNS_WINDOWS as readonly string[]).includes(value) || value === '24h') {
    return value as RunsWindow
  }
  return undefined
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

function parseWorkersFailedSearch(search: Record<string, unknown>): WorkersFailedSearch {
  const parsed: WorkersFailedSearch = {}
  const window = parseWorkersWindow(search.window)
  if (window) parsed.window = window
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

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  validateSearch: (search: Record<string, unknown>) => {
    const parsed: { tab: PipelineTab; process?: number } = {
      tab: parsePipelineTab(search.tab),
    }
    const process = parseProcessId(search.process)
    if (process != null) parsed.process = process
    return parsed
  },
  component: DashboardPage,
})

export type RequestsSearch = {
  source?: 'webform' | 'drop' | 'csv' | 'manual'
  state?: string
  attention?: 'needs' | 'clear'
  raw?: 'yes' | 'no'
  q?: string
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
  if (typeof search.state === 'string' && search.state.trim()) {
    parsed.state = search.state.trim().toUpperCase()
  }
  if (search.attention === 'needs' || search.attention === 'clear') {
    parsed.attention = search.attention
  }
  if (search.raw === 'yes' || search.raw === 'no') {
    parsed.raw = search.raw
  }
  if (typeof search.q === 'string' && search.q.trim()) {
    parsed.q = search.q.trim()
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

const needsAttentionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/requests/needs-attention',
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
  validateSearch: (search: Record<string, unknown>) => parseWorkersFailedSearch(search),
  component: WorkersFailedPage,
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
  validateSearch: (search: Record<string, unknown>) => parseWorkersFailedSearch(search),
  component: WorkerDetailPage,
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
  validateSearch: (search: Record<string, unknown>) => {
    const parsed: { tab: PipelineTab; process?: number } = {
      tab: parsePipelineTab(search.tab),
    }
    const process = parseProcessId(search.process)
    if (process != null) parsed.process = process
    return parsed
  },
  beforeLoad: ({ search }) => {
    throw redirect({
      to: '/',
      search: { tab: search.tab, process: search.process },
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
