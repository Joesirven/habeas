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
])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
