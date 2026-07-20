import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/router-devtools'

import { AppShell } from '@/components/AppShell'
import { MatchingReviewPage } from '@/routes/approvals/matching-review'
import { DashboardPage } from '@/routes/index'
import { OpsDashboardPage } from '@/routes/ops/dashboard'
import { DropPipelinePage } from '@/routes/ops/drop-pipeline'
import { OpsIncidentsPage } from '@/routes/ops/incidents'
import { OpsJobsPage } from '@/routes/ops/jobs'
import { OpsRunsPage } from '@/routes/ops/runs'
import { RunDetailPage } from '@/routes/ops/run-detail'
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
  'configurations',
] as const

export type PipelineTab = (typeof PIPELINE_TABS)[number]

function parsePipelineTab(value: unknown): PipelineTab {
  if (typeof value === 'string' && PIPELINE_TABS.includes(value as PipelineTab)) {
    return value as PipelineTab
  }
  return 'home'
}

export const RUNS_WINDOWS = ['8h', '24h', '1w'] as const
export type RunsWindow = (typeof RUNS_WINDOWS)[number]

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

export const DEFAULT_RUNS_WINDOW: RunsWindow = '24h'

function parseRunsWindow(value: unknown): RunsWindow | undefined {
  if (typeof value === 'string' && RUNS_WINDOWS.includes(value as RunsWindow)) {
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
  component: DashboardPage,
})

const requestsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/requests',
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
  component: MatchingReviewPage,
})

const opsDashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/dashboard',
  component: OpsDashboardPage,
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
  validateSearch: (search: Record<string, unknown>) => ({
    tab: parsePipelineTab(search.tab),
  }),
  component: DropPipelinePage,
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
