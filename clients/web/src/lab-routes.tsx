// @ts-nocheck — lab paths are omitted from the product Register (router casts labRoutes as []).
/**
 * Dev-only lab routes. Imported only from a Vite-droppable branch in router.tsx
 * (`VITE_ENABLE_LABS === 'true' || !import.meta.env.PROD`). Do not import this
 * module from product routes or from a top-level router import.
 */
import { createRoute, redirect, type AnyRoute } from '@tanstack/react-router'
import { lazy } from 'react'

import { DevLabsIndexPage } from '@/routes/dev/index'
import { PendingSettingsLabPage } from '@/routes/dev/pending-settings-lab'
import { SheetsCadenceLabPage } from '@/routes/dev/sheets-cadence-lab'
import {
  SheetsOauthLabPage,
  type SheetsOauthLabSearch,
} from '@/routes/dev/sheets-oauth'
import { DropProdCutoverLabPage } from '@/routes/dev/drop-prod-cutover'
import { TokenResourceServerLabPage } from '@/routes/dev/token-resource-server'
import {
  OwnerMapAlternativesPage,
  parseOwnerMapLabSearch,
} from '@/routes/dev/owner-map-alternatives'
import {
  MatchQualityLabPage,
  parseMatchQualityLabSearch,
} from '@/routes/dev/match-quality'

const MatchingResultsLabPage = lazy(() =>
  import('@/routes/requests/matching-results-lab').then((m) => ({
    default: m.MatchingResultsLabPage,
  })),
)

export function createLabRoutes(
  parent: AnyRoute,
  parseInboxSearch: (search: Record<string, unknown>) => Record<string, unknown>,
): AnyRoute[] {
  const matchingResultsLabRoute = createRoute({
    getParentRoute: () => parent,
    path: '/requests/matching-results-lab',
    validateSearch: (search: Record<string, unknown>) => parseInboxSearch(search),
    component: MatchingResultsLabPage,
  })

  const sheetsCadenceLabRoute = createRoute({
    getParentRoute: () => parent,
    path: '/dev/sheets-cadence-lab',
    component: SheetsCadenceLabPage,
  })

  const sheetsOauthLabRoute = createRoute({
    getParentRoute: () => parent,
    path: '/dev/sheets-oauth',
    validateSearch: (search: Record<string, unknown>): SheetsOauthLabSearch => ({
      code: typeof search.code === 'string' ? search.code : undefined,
      state: typeof search.state === 'string' ? search.state : undefined,
      error: typeof search.error === 'string' ? search.error : undefined,
    }),
    component: SheetsOauthLabPage,
  })

  const devLabsIndexRoute = createRoute({
    getParentRoute: () => parent,
    path: '/dev',
    component: DevLabsIndexPage,
  })

  const pendingSettingsLabRoute = createRoute({
    getParentRoute: () => parent,
    path: '/dev/pending-settings',
    component: PendingSettingsLabPage,
  })

  const dropProdCutoverLabRoute = createRoute({
    getParentRoute: () => parent,
    path: '/dev/drop-prod-cutover',
    component: DropProdCutoverLabPage,
  })

  const tokenResourceServerLabRoute = createRoute({
    getParentRoute: () => parent,
    path: '/dev/token-resource-server',
    component: TokenResourceServerLabPage,
  })

  /**
   * Wave M planned URL. No new lab page — the owner wizard already has
   * live-fail Retry / Set up manual upload and upload column mapping.
   */
  const ownerMapFallbackLabRoute = createRoute({
    getParentRoute: () => parent,
    path: '/dev/owner-map-fallback',
    beforeLoad: () => {
      throw redirect({ to: '/owner/connectors', replace: true })
    },
    component: () => null,
  })

  const ownerMapAlternativesLabRoute = createRoute({
    getParentRoute: () => parent,
    path: '/dev/owner-map-alternatives',
    validateSearch: (search: Record<string, unknown>) =>
      parseOwnerMapLabSearch(search),
    component: function OwnerMapAlternativesRoute() {
      const search = ownerMapAlternativesLabRoute.useSearch()
      return <OwnerMapAlternativesPage search={search} />
    },
  })

  const matchQualityLabRoute = createRoute({
    getParentRoute: () => parent,
    path: '/dev/match-quality',
    validateSearch: (search: Record<string, unknown>) =>
      parseMatchQualityLabSearch(search),
    component: function MatchQualityLabRoute() {
      const search = matchQualityLabRoute.useSearch()
      return <MatchQualityLabPage search={search} />
    },
  })

  return [
    matchingResultsLabRoute,
    devLabsIndexRoute,
    sheetsCadenceLabRoute,
    sheetsOauthLabRoute,
    pendingSettingsLabRoute,
    dropProdCutoverLabRoute,
    tokenResourceServerLabRoute,
    ownerMapFallbackLabRoute,
    ownerMapAlternativesLabRoute,
    matchQualityLabRoute,
  ]
}
