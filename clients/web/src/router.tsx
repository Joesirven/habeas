import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/router-devtools'

import { AppShell } from '@/components/AppShell'
import { MatchingReviewPage } from '@/routes/approvals/matching-review'
import { DashboardPage } from '@/routes/index'
import { ManualRequestPage } from '@/routes/requests/new'
import { RequestsPage } from '@/routes/requests/index'

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

const manualRequestRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/requests/new',
  component: ManualRequestPage,
})

const matchingReviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/approvals/matching-review',
  component: MatchingReviewPage,
})

const routeTree = rootRoute.addChildren([
  indexRoute,
  requestsRoute,
  manualRequestRoute,
  matchingReviewRoute,
])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
