// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { afterEach, describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { isDropProcessDetailQuery, mergeBulkProcessDetail } from './live-events'

const LIVE_EVENTS_SOURCE = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), 'live-events.ts'),
  'utf8',
)

const SAME_ORIGIN_SSE = '/api/live/events'

describe('Architecture B live-events SSE path', () => {
  test('hardcodes same-origin /api/live/events even when REST is cross-origin', () => {
    expect(LIVE_EVENTS_SOURCE).toContain(`const LIVE_EVENTS_PATH = '${SAME_ORIGIN_SSE}'`)
    expect(LIVE_EVENTS_SOURCE).not.toMatch(
      /LIVE_EVENTS_PATH\s*=\s*`\$\{import\.meta\.env\.VITE_ADMIN_API_URL/,
    )
    expect(LIVE_EVENTS_SOURCE).not.toMatch(/\?ticket=/)
  })

  test('uses native EventSource with no Authorization or init object', () => {
    expect(LIVE_EVENTS_SOURCE).toMatch(/new EventSource\(LIVE_EVENTS_PATH\)/)
    expect(LIVE_EVENTS_SOURCE).not.toMatch(/new EventSource\([^)]+,\s*\{/)
    expect(LIVE_EVENTS_SOURCE).not.toMatch(/withCredentials/)
    expect(LIVE_EVENTS_SOURCE).not.toMatch(/headers\s*:/)
  })

  test('skips EventSource when the hook is disabled', () => {
    expect(LIVE_EVENTS_SOURCE).toMatch(/if\s*\(\s*!enabled\s*\)\s*return/)
  })
})

describe('LIVE_EVENTS_PATH export', () => {
  const previousAdminApiUrl = process.env.VITE_ADMIN_API_URL

  afterEach(() => {
    if (previousAdminApiUrl === undefined) delete process.env.VITE_ADMIN_API_URL
    else process.env.VITE_ADMIN_API_URL = previousAdminApiUrl
  })

  test('stays /api/live/events when VITE_ADMIN_API_URL is a cross-origin REST host', async () => {
    process.env.VITE_ADMIN_API_URL = 'https://admin-api-dev.example'
    const { LIVE_EVENTS_PATH } = await import(
      `./live-events.ts?sse=${encodeURIComponent(crypto.randomUUID())}`
    )
    expect(LIVE_EVENTS_PATH).toBe(SAME_ORIGIN_SSE)
    expect(LIVE_EVENTS_PATH).not.toContain('admin-api-dev.example')
    expect(LIVE_EVENTS_PATH).not.toContain('ticket=')
    expect(LIVE_EVENTS_PATH).not.toMatch(/[?&]access_token=/)
  })
})

function stageCounts(overrides = {}) {
  return { total: 100, open: 40, success: 55, failed: 5, ...overrides }
}

/** Expanded-card cache shape — GET /ops/drop/processes/{id} (ids/counts only). */
function bulkDetailFixture() {
  return {
    process_id: 42,
    intake_source: 'drop',
    process_at: '2026-08-27T01:00:00.000Z',
    completed_at: null,
    label: 'Aug 27 · CA DROP',
    download_status: 'completed',
    raw_rows: 120,
    request_rows: 100,
    detail: 'lite',
    stages: {
      download: stageCounts({ total: 1, open: 0, success: 1, failed: 0 }),
      land: stageCounts({ total: 1, open: 0, success: 1, failed: 0 }),
      promote: stageCounts({ total: 1, open: 0, success: 1, failed: 0 }),
      matching: stageCounts(),
      review: stageCounts({ total: 20, open: 12, success: 8, failed: 0 }),
      fulfillment: stageCounts({ total: 8, open: 8, success: 0, failed: 0 }),
    },
    overall: { percent: 55, current_stage: 'matching', status: 'running' },
    verticals: [
      {
        vertical: 'data',
        label: 'Data',
        live: true,
        catalog_only: false,
        matching: { ...stageCounts(), in_flight: 12 },
      },
      {
        vertical: 'auth0',
        label: 'Auth0',
        live: true,
        catalog_only: false,
        matching: { ...stageCounts({ open: 60, success: 35 }), in_flight: 30 },
      },
    ],
  }
}

describe('isDropProcessDetailQuery', () => {
  test('matches the drop-pipeline expand-card key exactly', () => {
    // Mirror of drop-pipeline.tsx BatchProcessExpandRow detailQuery key.
    expect(isDropProcessDetailQuery(['admin-api', 'ops', 'drop-processes', 'detail', 42])).toBe(
      true,
    )
  })

  test('rejects list, snapshot, and malformed keys', () => {
    expect(isDropProcessDetailQuery(['admin-api', 'ops', 'drop-processes', 'recent-30d'])).toBe(
      false,
    )
    expect(
      isDropProcessDetailQuery(['admin-api', 'ops', 'drop-processes', 'pipeline-list', {}]),
    ).toBe(false)
    expect(isDropProcessDetailQuery(['admin-api', 'ops', 'drop-console', 'snapshot'])).toBe(false)
    expect(isDropProcessDetailQuery(['admin-api', 'ops', 'drop-processes'])).toBe(false)
    expect(isDropProcessDetailQuery(['admin-api', 'ops', 'drop-processes', 'detail', '42'])).toBe(
      false,
    )
    expect(isDropProcessDetailQuery(['admin-api', 'ops', 'drop-processes', 'detail'])).toBe(false)
  })
})

describe('mergeBulkProcessDetail', () => {
  test('merges stage counters per stage and leaves other stages untouched', () => {
    const old = bulkDetailFixture()
    const next = mergeBulkProcessDetail(old, {
      process_id: 42,
      stages: {
        matching: stageCounts({ open: 10, success: 85 }),
        review: stageCounts({ total: 20, open: 4, success: 16, failed: 0 }),
      },
    })
    expect(next.stages.matching).toEqual(stageCounts({ open: 10, success: 85 }))
    expect(next.stages.review).toEqual(stageCounts({ total: 20, open: 4, success: 16, failed: 0 }))
    expect(next.stages.fulfillment).toEqual(old.stages.fulfillment)
    expect(next.stages.download).toEqual(old.stages.download)
  })

  test('merges overall and keeps cached overall when the patch omits it', () => {
    const old = bulkDetailFixture()
    const patched = mergeBulkProcessDetail(old, {
      process_id: 42,
      overall: { percent: 83, current_stage: 'review', status: 'running' },
    })
    expect(patched.overall).toEqual({ percent: 83, current_stage: 'review', status: 'running' })

    const untouched = mergeBulkProcessDetail(old, { process_id: 42 })
    expect(untouched.overall).toEqual(old.overall)
    expect(untouched.stages).toEqual(old.stages)
  })

  test('applies scalar summary fields only when present', () => {
    const old = bulkDetailFixture()
    const next = mergeBulkProcessDetail(old, {
      process_id: 42,
      completed_at: '2026-08-27T02:00:00.000Z',
      download_status: 'completed',
      request_rows: 101,
    })
    expect(next.completed_at).toBe('2026-08-27T02:00:00.000Z')
    expect(next.request_rows).toBe(101)
    expect(next.label).toBe(old.label)
    expect(next.raw_rows).toBe(old.raw_rows)
    expect(next.intake_source).toBe(old.intake_source)
  })

  test('merges verticals by vertical key — updates, appends, preserves', () => {
    const old = bulkDetailFixture()
    const next = mergeBulkProcessDetail(old, {
      process_id: 42,
      verticals: [
        { vertical: 'auth0', matching: { ...stageCounts({ open: 20, success: 75 }), in_flight: 8 } },
        {
          vertical: 'communications',
          label: 'Communications',
          live: true,
          catalog_only: false,
          matching: { ...stageCounts({ open: 100, success: 0, failed: 0 }), in_flight: 0 },
        },
      ],
    })
    expect(next.verticals).toHaveLength(3)
    const rows = Object.fromEntries(next.verticals.map((row) => [row.vertical, row]))
    // Updated row keeps cached display fields, takes new counts incl. in_flight.
    expect(rows.auth0.label).toBe('Auth0')
    expect(rows.auth0.matching).toEqual({ ...stageCounts({ open: 20, success: 75 }), in_flight: 8 })
    // Cached row absent from the patch is preserved.
    expect(rows.data).toEqual(old.verticals[0])
    // New vertical appended.
    expect(rows.communications.live).toBe(true)
    expect(rows.communications.matching).toEqual({
      ...stageCounts({ open: 100, success: 0, failed: 0 }),
      in_flight: 0,
    })
  })

  test('keeps cached vertical stage counters when the patch row omits a stage', () => {
    const old = bulkDetailFixture()
    const next = mergeBulkProcessDetail(old, {
      process_id: 42,
      verticals: [{ vertical: 'data', review: { total: 4, open: 4, success: 0, failed: 0, in_flight: 0 } }],
    })
    const rows = Object.fromEntries(next.verticals.map((row) => [row.vertical, row]))
    expect(rows.data.matching).toEqual(old.verticals[0].matching)
    expect(rows.data.review).toEqual({ total: 4, open: 4, success: 0, failed: 0, in_flight: 0 })
  })

  test('never blanks cached verticals on an empty or missing patch array', () => {
    const old = bulkDetailFixture()
    const emptyPatch = mergeBulkProcessDetail(old, { process_id: 42, verticals: [] })
    expect(emptyPatch.verticals).toEqual(old.verticals)

    const missingPatch = mergeBulkProcessDetail(old, {
      process_id: 42,
      stages: { matching: stageCounts({ open: 5, success: 90 }) },
    })
    expect(missingPatch.verticals).toEqual(old.verticals)
  })

  test('seeds verticals when the cache has none yet', () => {
    const old = bulkDetailFixture()
    delete old.verticals
    const next = mergeBulkProcessDetail(old, {
      process_id: 42,
      verticals: [{ vertical: 'data', matching: stageCounts() }],
    })
    expect(next.verticals).toHaveLength(1)
    expect(next.verticals[0].vertical).toBe('data')
  })

  test('ignores malformed vertical rows instead of corrupting the cache', () => {
    const old = bulkDetailFixture()
    const next = mergeBulkProcessDetail(old, {
      process_id: 42,
      verticals: [null, { matching: stageCounts() }, { vertical: '' }, 7],
    })
    expect(next.verticals).toEqual(old.verticals)
  })

  test('does not mutate the cached detail', () => {
    const old = bulkDetailFixture()
    const snapshot = JSON.parse(JSON.stringify(old))
    mergeBulkProcessDetail(old, {
      process_id: 42,
      stages: { matching: stageCounts({ open: 1, success: 94 }) },
      overall: { percent: 99, current_stage: 'fulfillment', status: 'running' },
      verticals: [{ vertical: 'data', matching: stageCounts({ open: 1, success: 94 }) }],
    })
    expect(old).toEqual(snapshot)
  })
})

describe('bulk_process expand-detail wiring', () => {
  test('listener patches expanded-card detail queries and covers them in fallback', () => {
    expect(LIVE_EVENTS_SOURCE).toMatch(
      /const patchedDetail = patchBulkProcessDetailQueries\(queryClient, payload\)/,
    )
    expect(LIVE_EVENTS_SOURCE).toMatch(/!patchedList && !patchedSnapshot && !patchedDetail/)
  })

  test('detail patcher targets the detail segment keyed by process_id', () => {
    const patcher = LIVE_EVENTS_SOURCE.match(/function patchBulkProcessDetailQueries[\s\S]*?\n}/)
    expect(patcher).not.toBeNull()
    expect(patcher[0]).toContain('isDropProcessDetailQuery(query.queryKey)')
    expect(patcher[0]).toContain('query.queryKey[4] === patch.process_id')
  })

  test('detail patcher never seeds a cache entry from SSE alone', () => {
    const patcher = LIVE_EVENTS_SOURCE.match(/function patchBulkProcessDetailQueries[\s\S]*?\n}/)
    expect(patcher).not.toBeNull()
    expect(patcher[0]).toContain('if (!old) return old')
  })
})
