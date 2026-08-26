// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { afterEach, describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

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
