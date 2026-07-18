import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/router-devtools'
import type { ReactNode } from 'react'

import { AppShell } from '@/components/AppShell'
import { RequireRole } from '@/lib/auth'
import { SplashLabPage } from '@/routes/dev/splash-lab'
import { DashboardPage } from '@/routes/index'
import { OpsConfigurationPage } from '@/routes/ops/configuration'
import { OpsDashboardPage } from '@/routes/ops/dashboard'
import { DropPipelinePage } from '@/routes/ops/drop-pipeline'
import { HealthConfigurationPage } from '@/routes/ops/health/configuration'
import { HealthEscalationsPage } from '@/routes/ops/health/escalations'
import { HealthLandingPage } from '@/routes/ops/health/index'
import { OpsIncidentsPage } from '@/routes/ops/incidents'
import { OpsInsightsPage } from '@/routes/ops/insights'
import { OpsJobsPage } from '@/routes/ops/jobs'
import { OpsRunsPage } from '@/routes/ops/runs'
import { NeedsAttentionPage } from '@/routes/requests/needs-attention'
import { ManualRequestPage } from '@/routes/requests/new'
import { RequestsPage } from '@/routes/requests/index'

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

function SuperAdminGate({ children }: { children: ReactNode }) {
  return <RequireRole allow={['super_admin']}>{children}</RequireRole>
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

const splashLabRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/dev/splash-lab',
  component: SplashLabPage,
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

const manualRequestRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/requests/new',
  component: ManualRequestPage,
})

/** Compat: Matching review → Needs attention. */
const matchingReviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/approvals/matching-review',
  beforeLoad: () => {
    throw redirect({ to: '/requests/needs-attention' })
  },
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

const opsInsightsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/insights',
  component: OpsInsightsPage,
})

const opsIncidentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/incidents',
  component: OpsIncidentsPage,
})

const opsConfigurationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/configuration',
  component: OpsConfigurationPage,
})

const dropPipelineRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/drop-pipeline',
  validateSearch: (search: Record<string, unknown>) => ({
    tab: parsePipelineTab(search.tab),
  }),
  component: () => (
    <SuperAdminGate>
      <DropPipelinePage />
    </SuperAdminGate>
  ),
})

const healthRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/health',
  component: () => (
    <SuperAdminGate>
      <HealthLandingPage />
    </SuperAdminGate>
  ),
})

const healthEscalationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/health/escalations',
  component: () => (
    <SuperAdminGate>
      <HealthEscalationsPage />
    </SuperAdminGate>
  ),
})

const healthConfigurationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ops/health/configuration',
  component: () => (
    <SuperAdminGate>
      <HealthConfigurationPage />
    </SuperAdminGate>
  ),
})

const routeTree = rootRoute.addChildren([
  indexRoute,
  splashLabRoute,
  requestsRoute,
  needsAttentionRoute,
  manualRequestRoute,
  matchingReviewRoute,
  opsDashboardRoute,
  opsRunsRoute,
  opsJobsRoute,
  opsInsightsRoute,
  opsIncidentsRoute,
  opsConfigurationRoute,
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
