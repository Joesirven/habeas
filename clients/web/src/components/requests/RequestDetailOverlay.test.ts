// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import {
  CATALOG_ONLY_NOT_LIVE_LABEL,
  JourneyStageSubsteps,
  clusterRowStatusLabel,
} from './RequestDetailOverlay'

describe('clusterRowStatusLabel', () => {
  test('live rows keep workbench status labels', () => {
    expect(
      clusterRowStatusLabel({ live: true, blocker: null }, 'in_progress'),
    ).toBe('In progress')
    expect(
      clusterRowStatusLabel(
        { live: true, blocker: 'Catalog-only — matching is not live' },
        'complete',
      ),
    ).toBe('Complete')
  })

  test('not-live rows use API catalog-only copy, never Soon', () => {
    expect(
      clusterRowStatusLabel(
        { live: false, blocker: 'Catalog-only — matching is not live' },
        'not_started',
      ),
    ).toBe('Catalog-only — matching is not live')
    expect(
      clusterRowStatusLabel(
        { live: false, blocker: 'Axios HQ matching is not live.' },
        'not_started',
      ),
    ).toBe('Axios HQ matching is not live.')
    expect(clusterRowStatusLabel({ live: false, blocker: null }, 'not_started')).toBe(
      CATALOG_ONLY_NOT_LIVE_LABEL,
    )
    expect(clusterRowStatusLabel({ live: false, blocker: '  ' }, 'waiting')).toBe(
      CATALOG_ONLY_NOT_LIVE_LABEL,
    )
    expect(
      clusterRowStatusLabel({ live: false, blocker: '2 not started' }, 'not_started'),
    ).toBe(CATALOG_ONLY_NOT_LIVE_LABEL)
    expect(clusterRowStatusLabel({ live: false, blocker: null }, 'not_started')).not.toBe(
      'Soon',
    )
  })
})

describe('JourneyStageSubsteps catalog-only cluster rows', () => {
  const stages = [
    { stage: 'ingest', label: 'Ingest', status: 'complete' as const, blocker: null },
    { stage: 'matching', label: 'Matching', status: 'in_progress' as const, blocker: null },
    { stage: 'fulfillment', label: 'Fulfillment', status: 'not_started' as const, blocker: null },
    { stage: 'notice', label: 'Notice', status: 'not_started' as const, blocker: null },
  ]

  test('matching rail stamps API not-live language instead of Soon', () => {
    const html = renderToStaticMarkup(
      createElement(JourneyStageSubsteps, {
        stages,
        stageKey: 'matching',
        matchingCluster: [
          {
            vertical: 'data',
            label: 'Data',
            live: true,
            matching_status: 'in_progress',
            fulfillment_status: null,
            blocker: null,
          },
          {
            vertical: 'axios_hq',
            label: 'Axios HQ',
            live: false,
            matching_status: 'not_started',
            fulfillment_status: null,
            blocker: 'Catalog-only — matching is not live',
          },
        ],
      }),
    )
    expect(html).toContain('In progress')
    expect(html).toContain('Catalog-only — matching is not live')
    expect(html).toContain('Axios HQ: Catalog-only — matching is not live')
    expect(html).not.toContain('Soon')
    expect(html).not.toContain('Due soon')
  })

  test('fulfillment rail uses the same catalog-only copy when not live', () => {
    const html = renderToStaticMarkup(
      createElement(JourneyStageSubsteps, {
        stages,
        stageKey: 'fulfillment',
        fulfillmentCluster: [
          {
            vertical: 'lever',
            label: 'Lever',
            live: false,
            matching_status: 'not_started',
            fulfillment_status: 'not_started',
            blocker: null,
          },
        ],
      }),
    )
    expect(html).toContain(CATALOG_ONLY_NOT_LIVE_LABEL)
    expect(html).not.toContain('Soon')
  })
})
