// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { plugin } from 'bun'
import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

plugin({
  name: 'at-alias',
  setup(build) {
    build.onResolve({ filter: /^@\// }, (args) => ({
      path: join(import.meta.dir, '..', args.path.slice(2)),
    }))
  },
})

const ME_OK = {
  email: 'ops@example.com',
  role: 'admin',
}

function jwtWithExp(expSeconds: number): string {
  const encode = (value: object) =>
    btoa(JSON.stringify(value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${encode({ alg: 'none', typ: 'JWT' })}.${encode({ exp: expSeconds })}.sig`
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function headerValue(headers: unknown, name: string): string | null {
  if (headers == null) return null
  if (headers instanceof Headers) return headers.get(name)
  if (typeof headers !== 'object') return null
  const record = headers as Record<string, string>
  const key = Object.keys(record).find((k) => k.toLowerCase() === name.toLowerCase())
  return key ? String(record[key]) : null
}

function fetchCall(fetchMock: ReturnType<typeof mock>) {
  const [url, init] = fetchMock.mock.calls[0] ?? []
  return { url: String(url), init: init ?? {} }
}

function dpraTimingLogs(infoMock: ReturnType<typeof mock>) {
  const found: Array<Record<string, unknown>> = []
  for (const args of infoMock.mock.calls) {
    for (const arg of args) {
      if (arg && typeof arg === 'object' && arg.prefix === 'dpra-timing') {
        found.push(arg as Record<string, unknown>)
      }
    }
  }
  return found
}

function loggedStrings(infoMock: ReturnType<typeof mock>): string[] {
  return infoMock.mock.calls.flatMap((args) =>
    args.map((arg) => (typeof arg === 'string' ? arg : JSON.stringify(arg))),
  )
}

function installSessionStorage() {
  const store = new Map<string, string>()
  globalThis.sessionStorage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, String(value))
    },
    removeItem: (key: string) => {
      store.delete(key)
    },
    clear: () => {
      store.clear()
    },
    get length() {
      return store.size
    },
    key: (index: number) => [...store.keys()][index] ?? null,
  }
}

async function importApi(
  adminApiUrl: string | undefined,
  extraEnv: { VITE_GOOGLE_CLIENT_ID?: string; VITE_GIS_CLIENT_ID?: string } = {},
) {
  const previous = {
    VITE_ADMIN_API_URL: process.env.VITE_ADMIN_API_URL,
    VITE_GOOGLE_CLIENT_ID: process.env.VITE_GOOGLE_CLIENT_ID,
    VITE_GIS_CLIENT_ID: process.env.VITE_GIS_CLIENT_ID,
  }
  if (adminApiUrl === undefined) {
    delete process.env.VITE_ADMIN_API_URL
  } else {
    process.env.VITE_ADMIN_API_URL = adminApiUrl
  }
  if (extraEnv.VITE_GOOGLE_CLIENT_ID === undefined) {
    delete process.env.VITE_GOOGLE_CLIENT_ID
  } else {
    process.env.VITE_GOOGLE_CLIENT_ID = extraEnv.VITE_GOOGLE_CLIENT_ID
  }
  if (extraEnv.VITE_GIS_CLIENT_ID === undefined) {
    delete process.env.VITE_GIS_CLIENT_ID
  } else {
    process.env.VITE_GIS_CLIENT_ID = extraEnv.VITE_GIS_CLIENT_ID
  }
  const cacheKey = `${adminApiUrl === undefined ? 'unset' : adminApiUrl || 'empty'}-${crypto.randomUUID()}`
  try {
    return await import(`./api.ts?admin-api-auth=${encodeURIComponent(cacheKey)}`)
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }
}

describe('Architecture B admin-api client', () => {
  const originalFetch = globalThis.fetch
  let fetchMock: ReturnType<typeof mock>

  beforeEach(() => {
    installSessionStorage()
    fetchMock = mock(async () => jsonResponse({ ...ME_OK, real_role: 'admin' }))
    globalThis.fetch = fetchMock
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    sessionStorage.clear()
  })

  test('empty VITE_ADMIN_API_URL uses same-origin /api and no Bearer', async () => {
    const { fetchAdminApi } = await importApi(undefined)
    await fetchAdminApi('/me')
    const { url, init } = fetchCall(fetchMock)
    expect(url).toBe('/api/me')
    expect(headerValue(init.headers, 'Authorization')).toBeNull()
  })

  test('empty-string VITE_ADMIN_API_URL still falls back to /api', async () => {
    const { fetchAdminApi } = await importApi('')
    await fetchAdminApi('/readyz')
    expect(fetchCall(fetchMock).url).toBe('/api/readyz')
  })

  test('set VITE_ADMIN_API_URL calls that origin with Authorization Bearer', async () => {
    const origin = 'https://admin-api-dev.example'
    const token = 'test-user-id-token'
    const { fetchAdminApi, setAdminApiUserToken } = await importApi(origin)
    setAdminApiUserToken(token)
    await fetchAdminApi('/me')
    const { url, init } = fetchCall(fetchMock)
    expect(url).toBe(`${origin}/me`)
    expect(headerValue(init.headers, 'Authorization')).toBe(`Bearer ${token}`)
  })

  test('set VITE_ADMIN_API_URL without a user token uses same-origin /api IAP fallback', async () => {
    const { fetchAdminApi, adminApiRequestUrl } = await importApi(
      'https://admin-api-dev.example',
    )
    expect(adminApiRequestUrl('/me')).toBe('/api/me')
    await fetchAdminApi('/me')
    expect(fetchCall(fetchMock).url).toBe('/api/me')
    expect(headerValue(fetchCall(fetchMock).init.headers, 'Authorization')).toBeNull()
  })

  test('same-origin /api never attaches Bearer even when a token is in memory', async () => {
    const { fetchAdminApi, setAdminApiUserToken } = await importApi(undefined)
    setAdminApiUserToken('must-not-be-sent')
    await fetchAdminApi('/me')
    expect(fetchCall(fetchMock).url).toBe('/api/me')
    expect(headerValue(fetchCall(fetchMock).init.headers, 'Authorization')).toBeNull()
  })

  test('listDropBulkProcesses uses the 8s fast-query timeout, not 30s', async () => {
    const originalTimeout = AbortSignal.timeout
    const timeoutMs: number[] = []
    AbortSignal.timeout = ((ms: number) => {
      timeoutMs.push(ms)
      return originalTimeout.call(AbortSignal, ms)
    }) as typeof AbortSignal.timeout
    try {
      const { listDropBulkProcesses, OPS_FAST_QUERY_TIMEOUT_MS, OPS_QUERY_TIMEOUT_MS } =
        await importApi(undefined)
      expect(OPS_FAST_QUERY_TIMEOUT_MS).toBe(8_000)
      expect(OPS_QUERY_TIMEOUT_MS).toBe(30_000)
      await listDropBulkProcesses({
        days: 7,
        intake_source: 'drop',
        include_summary: true,
        limit: 50,
      })
      expect(timeoutMs).toContain(8_000)
      expect(timeoutMs).not.toContain(30_000)
      expect(fetchCall(fetchMock).url).toContain('/ops/drop/processes')
      expect(fetchCall(fetchMock).url).toContain('include_summary=true')
    } finally {
      AbortSignal.timeout = originalTimeout
    }
  })

  test('listDropBulkProcesses omits include_summary unless requested', async () => {
    const { listDropBulkProcesses } = await importApi(undefined)
    await listDropBulkProcesses({ days: 7, intake_source: 'drop', limit: 50 })
    expect(fetchCall(fetchMock).url).toContain('/ops/drop/processes')
    expect(fetchCall(fetchMock).url).not.toContain('include_summary=')
  })

  test('getDropBulkProcess defaults to lite detail and 8s timeout', async () => {
    const originalTimeout = AbortSignal.timeout
    const timeoutMs: number[] = []
    AbortSignal.timeout = ((ms: number) => {
      timeoutMs.push(ms)
      return originalTimeout.call(AbortSignal, ms)
    }) as typeof AbortSignal.timeout
    try {
      const { getDropBulkProcess, OPS_FAST_QUERY_TIMEOUT_MS, OPS_EXPAND_DETAIL_TIMEOUT_MS } =
        await importApi(undefined)
      expect(OPS_FAST_QUERY_TIMEOUT_MS).toBe(8_000)
      await getDropBulkProcess(25)
      expect(timeoutMs).toContain(8_000)
      expect(timeoutMs).not.toContain(OPS_EXPAND_DETAIL_TIMEOUT_MS)
      expect(fetchCall(fetchMock).url).toContain('/ops/drop/processes/25')
      expect(fetchCall(fetchMock).url).toContain('detail=lite')
    } finally {
      AbortSignal.timeout = originalTimeout
    }
  })

  test('listDropBulkProcessRuns defaults to lite detail and 8s timeout', async () => {
    const originalTimeout = AbortSignal.timeout
    const timeoutMs: number[] = []
    AbortSignal.timeout = ((ms: number) => {
      timeoutMs.push(ms)
      return originalTimeout.call(AbortSignal, ms)
    }) as typeof AbortSignal.timeout
    try {
      const { listDropBulkProcessRuns, OPS_FAST_QUERY_TIMEOUT_MS } = await importApi(undefined)
      await listDropBulkProcessRuns({ stage: 'matching', days: 7 })
      expect(timeoutMs).toContain(OPS_FAST_QUERY_TIMEOUT_MS)
      expect(fetchCall(fetchMock).url).toContain('/ops/drop/processes/runs')
      expect(fetchCall(fetchMock).url).toContain('detail=lite')
      expect(fetchCall(fetchMock).url).toContain('stage=matching')
    } finally {
      AbortSignal.timeout = originalTimeout
    }
  })

  test.each([
    [
      'listOwnerVisibleVerticals',
      (api: Awaited<ReturnType<typeof importApi>>) => api.listOwnerVisibleVerticals(),
      '/owner/verticals',
    ],
    [
      'listOwnerConnectors',
      (api: Awaited<ReturnType<typeof importApi>>) => api.listOwnerConnectors('people_hr'),
      '/owner/verticals/people_hr/connectors',
    ],
    [
      'listOwnerConnectorReminders',
      (api: Awaited<ReturnType<typeof importApi>>) => api.listOwnerConnectorReminders(),
      '/owner/connector-reminders',
    ],
  ])('%s uses the 8s fast-query timeout, not 30s', async (_name, call, path) => {
    const originalTimeout = AbortSignal.timeout
    const timeoutMs: number[] = []
    AbortSignal.timeout = ((ms: number) => {
      timeoutMs.push(ms)
      return originalTimeout.call(AbortSignal, ms)
    }) as typeof AbortSignal.timeout
    try {
      const api = await importApi(undefined)
      expect(api.OPS_FAST_QUERY_TIMEOUT_MS).toBe(8_000)
      expect(api.OPS_QUERY_TIMEOUT_MS).toBe(30_000)
      await call(api)
      expect(timeoutMs).toContain(8_000)
      expect(timeoutMs).not.toContain(30_000)
      expect(fetchCall(fetchMock).url).toContain(path)
    } finally {
      AbortSignal.timeout = originalTimeout
    }
  })

  test.each([
    ['getMe', () => importApi(undefined).then((api) => api.getMe()), '/me'],
    [
      'getDropConsoleSnapshot',
      () => importApi(undefined).then((api) => api.getDropConsoleSnapshot()),
      '/ops/drop/console/snapshot',
    ],
    [
      'getDropPipelineSummary',
      () => importApi(undefined).then((api) => api.getDropPipelineSummary()),
      '/ops/drop/pipeline/summary',
    ],
    [
      'listConnections',
      () => importApi(undefined).then((api) => api.listConnections()),
      '/ops/connections',
    ],
    [
      'listOwnerConnectors',
      () =>
        importApi(undefined).then((api) => api.listOwnerConnectors('people_hr')),
      '/owner/verticals/people_hr/connectors',
    ],
    [
      'listOwnerConnectors tech',
      () => importApi(undefined).then((api) => api.listOwnerConnectors('tech')),
      '/owner/verticals/tech/connectors',
    ],
  ])('%s first-paint GET uses the 8s SPA timeout', async (_name, call, path) => {
    const originalTimeout = AbortSignal.timeout
    const timeoutMs: number[] = []
    AbortSignal.timeout = ((ms: number) => {
      timeoutMs.push(ms)
      return originalTimeout.call(AbortSignal, ms)
    }) as typeof AbortSignal.timeout
    try {
      const { OPS_FAST_QUERY_TIMEOUT_MS, OPS_PROD_PROBE_MAX_MS, OPS_ME_PROD_MAX_MS } =
        await importApi(undefined)
      expect(OPS_FAST_QUERY_TIMEOUT_MS).toBe(8_000)
      expect(OPS_PROD_PROBE_MAX_MS).toBe(5_000)
      expect(OPS_ME_PROD_MAX_MS).toBe(2_000)
      await call()
      expect(timeoutMs).toContain(8_000)
      expect(timeoutMs).not.toContain(30_000)
      expect(fetchCall(fetchMock).url).toContain(path)
    } finally {
      AbortSignal.timeout = originalTimeout
    }
  })

  test('getMe applies the 8s fast-query timeout', async () => {
    const originalTimeout = AbortSignal.timeout
    const timeoutMs: number[] = []
    AbortSignal.timeout = ((ms: number) => {
      timeoutMs.push(ms)
      return originalTimeout.call(AbortSignal, ms)
    }) as typeof AbortSignal.timeout
    try {
      const { getMe, OPS_FAST_QUERY_TIMEOUT_MS } = await importApi(undefined)
      expect(OPS_FAST_QUERY_TIMEOUT_MS).toBe(8_000)
      await getMe()
      expect(timeoutMs).toContain(8_000)
    } finally {
      AbortSignal.timeout = originalTimeout
    }
  })

  test('getMe timeout error names the path and 8s budget', async () => {
    fetchMock = mock(async () => {
      throw new DOMException('The operation was aborted due to timeout', 'TimeoutError')
    })
    globalThis.fetch = fetchMock
    const { getMe } = await importApi(undefined)
    expect(getMe()).rejects.toThrow(/timed out after 8000ms: \/me/)
  })

  test('getNeedsAttention uses the 30s ops-query timeout, not 8s', async () => {
    const originalTimeout = AbortSignal.timeout
    const timeoutMs: number[] = []
    AbortSignal.timeout = ((ms: number) => {
      timeoutMs.push(ms)
      return originalTimeout.call(AbortSignal, ms)
    }) as typeof AbortSignal.timeout
    try {
      const { getNeedsAttention, OPS_QUERY_TIMEOUT_MS, OPS_FAST_QUERY_TIMEOUT_MS } =
        await importApi(undefined)
      expect(OPS_QUERY_TIMEOUT_MS).toBe(30_000)
      await getNeedsAttention({ kind: 'matching', limit: 100 })
      expect(timeoutMs).toContain(30_000)
      expect(timeoutMs).not.toContain(OPS_FAST_QUERY_TIMEOUT_MS)
      expect(fetchCall(fetchMock).url).toContain('/ops/requests/needs-attention')
      expect(fetchCall(fetchMock).url).toContain('kind=matching')
    } finally {
      AbortSignal.timeout = originalTimeout
    }
  })

  test('getOwnerMatchingNeedsAttention inherits the 30s timeout', async () => {
    const originalTimeout = AbortSignal.timeout
    const timeoutMs: number[] = []
    AbortSignal.timeout = ((ms: number) => {
      timeoutMs.push(ms)
      return originalTimeout.call(AbortSignal, ms)
    }) as typeof AbortSignal.timeout
    try {
      const { getOwnerMatchingNeedsAttention } = await importApi(undefined)
      await getOwnerMatchingNeedsAttention({ limit: 100 })
      expect(timeoutMs).toContain(30_000)
      expect(fetchCall(fetchMock).url).toContain('/ops/requests/needs-attention')
      expect(fetchCall(fetchMock).url).toContain('kind=matching')
    } finally {
      AbortSignal.timeout = originalTimeout
    }
  })

  test('getOwnerFulfillmentNeedsAttention bounds both legs at 30s', async () => {
    const originalTimeout = AbortSignal.timeout
    const timeoutMs: number[] = []
    AbortSignal.timeout = ((ms: number) => {
      timeoutMs.push(ms)
      return originalTimeout.call(AbortSignal, ms)
    }) as typeof AbortSignal.timeout
    fetchMock = mock(async (input: unknown) => {
      const url = String(input)
      if (url.includes('/approvals')) return jsonResponse([])
      return jsonResponse({ items: [], total: 0, limit: 200, offset: 0 })
    })
    globalThis.fetch = fetchMock
    try {
      const { getOwnerFulfillmentNeedsAttention } = await importApi(undefined)
      const page = await getOwnerFulfillmentNeedsAttention({ limit: 50 })
      expect(page.items).toEqual([])
      const urls = fetchMock.mock.calls.map((call) => String(call[0]))
      expect(urls.some((url) => url.includes('/requests?'))).toBe(true)
      expect(urls.some((url) => url.includes('stage=fulfillment'))).toBe(true)
      expect(urls.some((url) => url.includes('/approvals?'))).toBe(true)
      expect(timeoutMs.filter((ms) => ms === 30_000)).toHaveLength(2)
    } finally {
      AbortSignal.timeout = originalTimeout
    }
  })

  test('getNeedsAttention timeout error names the path and 30s budget', async () => {
    fetchMock = mock(async () => {
      throw new DOMException('The operation was aborted due to timeout', 'TimeoutError')
    })
    globalThis.fetch = fetchMock
    const { getNeedsAttention } = await importApi(undefined)
    await expect(getNeedsAttention({ kind: 'matching' })).rejects.toThrow(
      /timed out after 30000ms: \/ops\/requests\/needs-attention/,
    )
  })

  test('getMe fills real_role from role when the API omits it', async () => {
    fetchMock = mock(async () => jsonResponse(ME_OK))
    globalThis.fetch = fetchMock
    const { getMe } = await importApi(undefined)
    await expect(getMe()).resolves.toEqual({
      email: 'ops@example.com',
      role: 'admin',
      real_role: 'admin',
    })
  })

  test('sends X-Dev-Simulate-Role from sessionStorage', async () => {
    const { fetchAdminApi, SIMULATE_ROLE_STORAGE_KEY } = await importApi(undefined)
    sessionStorage.setItem(SIMULATE_ROLE_STORAGE_KEY, 'data_user')
    await fetchAdminApi('/me')
    expect(headerValue(fetchCall(fetchMock).init.headers, 'X-Dev-Simulate-Role')).toBe(
      'data_user',
    )
  })

  test('googleIdentityServicesClientId is empty without Vite env', async () => {
    const { googleIdentityServicesClientId } = await importApi(
      'https://admin-api-dev.example',
    )
    expect(googleIdentityServicesClientId()).toBe('')
  })

  test('googleIdentityServicesClientId reads VITE_GOOGLE_CLIENT_ID', async () => {
    const { googleIdentityServicesClientId } = await importApi(
      'https://admin-api-dev.example',
      { VITE_GOOGLE_CLIENT_ID: '  web-client.apps.googleusercontent.com  ' },
    )
    expect(googleIdentityServicesClientId()).toBe('web-client.apps.googleusercontent.com')
  })

  test('googleIdentityServicesClientId falls back to VITE_GIS_CLIENT_ID', async () => {
    const { googleIdentityServicesClientId } = await importApi(
      'https://admin-api-dev.example',
      { VITE_GIS_CLIENT_ID: 'gis-client.apps.googleusercontent.com' },
    )
    expect(googleIdentityServicesClientId()).toBe('gis-client.apps.googleusercontent.com')
  })

  test('non-JWT lab tokens do not look expired', async () => {
    const { setAdminApiUserToken, adminApiUserTokenNeedsRefresh } = await importApi(
      'https://admin-api-dev.example',
    )
    setAdminApiUserToken('test-user-id-token')
    expect(adminApiUserTokenNeedsRefresh()).toBe(false)
  })

  test('JWT near expiry remints before fetchAdminApi attaches Bearer', async () => {
    const origin = 'https://admin-api-dev.example'
    const stale = jwtWithExp(Math.floor(Date.now() / 1000) + 10)
    const fresh = 'reminted-user-id-token'
    const api = await importApi(origin)
    api.setAdminApiUserToken(stale)
    expect(api.adminApiUserTokenNeedsRefresh()).toBe(true)
    const refresher = mock(async () => {
      api.setAdminApiUserToken(fresh)
    })
    api.registerAdminApiUserTokenRefresher(refresher)
    await api.fetchAdminApi('/me')
    expect(refresher).toHaveBeenCalledTimes(1)
    expect(headerValue(fetchCall(fetchMock).init.headers, 'Authorization')).toBe(
      `Bearer ${fresh}`,
    )
  })

  test('fresh JWT does not remint on fetch', async () => {
    const token = jwtWithExp(Math.floor(Date.now() / 1000) + 3_600)
    const api = await importApi('https://admin-api-dev.example')
    api.setAdminApiUserToken(token)
    const refresher = mock(async () => {
      throw new Error('should not remint')
    })
    api.registerAdminApiUserTokenRefresher(refresher)
    await api.fetchAdminApi('/me')
    expect(refresher).not.toHaveBeenCalled()
    expect(headerValue(fetchCall(fetchMock).init.headers, 'Authorization')).toBe(
      `Bearer ${token}`,
    )
  })

  test('same-origin /api never remints even when JWT is stale', async () => {
    const stale = jwtWithExp(Math.floor(Date.now() / 1000) + 10)
    const api = await importApi(undefined)
    api.setAdminApiUserToken(stale)
    const refresher = mock(async () => {
      throw new Error('same-origin must not remint')
    })
    api.registerAdminApiUserTokenRefresher(refresher)
    await api.fetchAdminApi('/me')
    expect(refresher).not.toHaveBeenCalled()
    expect(headerValue(fetchCall(fetchMock).init.headers, 'Authorization')).toBeNull()
  })

  test('fetchAdminApi logs a dpra-timing fetch object for /me', async () => {
    const originalInfo = console.info
    const infoMock = mock(() => {})
    console.info = infoMock
    try {
      const { fetchAdminApi } = await importApi(undefined)
      await fetchAdminApi('/me')
      const log = dpraTimingLogs(infoMock).find((entry) => entry.kind === 'fetch')
      expect(log).toBeDefined()
      expect(log?.prefix).toBe('dpra-timing')
      expect(log?.kind).toBe('fetch')
      expect(String(log?.url)).toContain('/me')
      expect(typeof log?.duration_ms).toBe('number')
      expect(Number.isFinite(log?.duration_ms)).toBe(true)
      expect(log?.status).toBe(200)
      expect(log?.abort).toBe(false)
    } finally {
      console.info = originalInfo
    }
  })

  test('fetchAdminApi timing abort is true on AbortError', async () => {
    const originalInfo = console.info
    const infoMock = mock(() => {})
    console.info = infoMock
    fetchMock = mock(async () => {
      throw new DOMException('The operation was aborted.', 'AbortError')
    })
    globalThis.fetch = fetchMock
    try {
      const { fetchAdminApi } = await importApi(undefined)
      await expect(fetchAdminApi('/me')).rejects.toThrow()
      const log = dpraTimingLogs(infoMock).find((entry) => entry.kind === 'fetch')
      expect(log).toBeDefined()
      expect(log?.prefix).toBe('dpra-timing')
      expect(log?.kind).toBe('fetch')
      expect(log?.abort).toBe(true)
    } finally {
      console.info = originalInfo
    }
  })

  test('fetchAdminApi timing abort is true on TimeoutError', async () => {
    const originalInfo = console.info
    const infoMock = mock(() => {})
    console.info = infoMock
    fetchMock = mock(async () => {
      throw new DOMException('The operation was aborted due to timeout', 'TimeoutError')
    })
    globalThis.fetch = fetchMock
    try {
      const { fetchAdminApi } = await importApi(undefined)
      await expect(fetchAdminApi('/me', { timeoutMs: 8_000 })).rejects.toThrow(
        /timed out after 8000ms: \/me/,
      )
      const log = dpraTimingLogs(infoMock).find((entry) => entry.kind === 'fetch')
      expect(log).toBeDefined()
      expect(log?.prefix).toBe('dpra-timing')
      expect(log?.kind).toBe('fetch')
      expect(log?.abort).toBe(true)
    } finally {
      console.info = originalInfo
    }
  })

  test('listOwnerConnectors uses the 8s fast abort', async () => {
    const { listOwnerConnectors, OPS_FAST_QUERY_TIMEOUT_MS } = await importApi(undefined)
    expect(OPS_FAST_QUERY_TIMEOUT_MS).toBe(8_000)
    await listOwnerConnectors('tech')
    const { url, init } = fetchCall(fetchMock)
    expect(url).toContain('/owner/verticals/tech/connectors')
    expect(init.signal).toBeDefined()
  })

  test('fetchAdminApi timing redacts email path segments and logs no PII', async () => {
    const originalInfo = console.info
    const infoMock = mock(() => {})
    console.info = infoMock
    try {
      const { fetchAdminApi } = await importApi(undefined)
      await fetchAdminApi('/legal/team/ops@example.com')
      for (const value of loggedStrings(infoMock)) {
        expect(value).not.toContain('ops@example.com')
        expect(value).not.toMatch(/[A-Za-z0-9._%+-]+@example\.com/)
      }
      const log = dpraTimingLogs(infoMock).find((entry) => entry.kind === 'fetch')
      expect(log).toBeDefined()
      expect(String(log?.url)).toContain('[redacted]')
      expect(String(log?.url)).not.toContain('ops@example.com')
    } finally {
      console.info = originalInfo
    }
  })
})

describe('collapsedPipelineCardFields', () => {
  test('maps complete overall, percent, and request rows', async () => {
    const { collapsedPipelineCardFields } = await importApi(undefined)
    const fields = collapsedPipelineCardFields({
      process_id: 1,
      intake_source: 'drop',
      process_at: '2026-08-21T12:00:00Z',
      completed_at: null,
      download_status: 'success',
      label: 'Aug 21 · CA DROP',
      linkable: true,
      overall: { percent: 100, status: 'complete', current_stage: 'fulfillment' },
      request_rows: 12,
    })
    expect(fields.status).toBe('complete')
    expect(fields.percent).toBe(100)
    expect(fields.requestRows).toBe(12)
    expect(fields.currentStage).toBe('fulfillment')
  })

  test('uses download_status and label when process_at is missing', async () => {
    const { collapsedPipelineCardFields } = await importApi(undefined)
    const fields = collapsedPipelineCardFields({
      process_id: 2,
      intake_source: 'drop',
      process_at: null,
      completed_at: null,
      download_status: 'success',
      label: 'Aug 21 · CA DROP',
      linkable: true,
    })
    expect(fields.status).toBe('success')
    expect(fields.title).toBe('Aug 21 · CA DROP')
  })

  test('never includes email fields', async () => {
    const { collapsedPipelineCardFields } = await importApi(undefined)
    const fields = collapsedPipelineCardFields({
      process_id: 3,
      intake_source: 'drop',
      process_at: null,
      completed_at: null,
      download_status: 'success',
      label: 'Aug 21 · CA DROP',
      linkable: true,
      email: 'ops@example.com',
      contact_email: 'ops@example.com',
    })
    expect(fields).not.toHaveProperty('email')
    expect(fields).not.toHaveProperty('contact_email')
    for (const key of Object.keys(fields)) {
      expect(key.toLowerCase()).not.toContain('email')
    }
    expect(JSON.stringify(fields)).not.toContain('ops@example.com')
    expect(JSON.stringify(fields)).not.toMatch(/[A-Za-z0-9._%+-]+@example\.com/)
  })
})

describe('GIS script load (P1 hang)', () => {
  const originalDocument = globalThis.document
  const originalWindow = globalThis.window
  const originalLocation = globalThis.location
  const originalWindowLocation = globalThis.window?.location
  const originalGoogle = globalThis.window?.google
  const originalWindowSetTimeout = globalThis.window?.setTimeout
  const originalWindowClearTimeout = globalThis.window?.clearTimeout

  function restoreGlobal(name, original) {
    if (original === undefined) delete globalThis[name]
    else globalThis[name] = original
  }

  function installDocument(existing?: {
    src: string
    readyState?: string
    complete?: boolean
  }) {
    const listeners = new Map<string, Array<() => void>>()
    const script = existing
      ? {
          src: existing.src,
          readyState: existing.readyState,
          complete: existing.complete,
          addEventListener: (type: string, fn: () => void) => {
            const list = listeners.get(type) ?? []
            list.push(fn)
            listeners.set(type, list)
          },
        }
      : null
    const created: Array<{ src: string; onload: (() => void) | null }> = []
    const doc = {
      querySelector: (sel: string) => {
        if (script && sel.includes('gsi/client')) return script
        return null
      },
      createElement: (tag: string) => {
        const el = { src: '', async: false, onload: null, onerror: null }
        if (tag === 'script') created.push(el)
        return el
      },
      head: {
        appendChild: (el: { src: string }) => el,
      },
    }
    globalThis.document = doc
    if (!globalThis.window) {
      globalThis.window = globalThis
    }
    globalThis.window.setTimeout = setTimeout
    globalThis.window.clearTimeout = clearTimeout
    return { script, created, listeners }
  }

  afterEach(() => {
    restoreGlobal('document', originalDocument)
    restoreGlobal('location', originalLocation)
    if (originalWindow === undefined) {
      delete globalThis.window
      delete globalThis.google
    } else {
      globalThis.window = originalWindow
      if (originalGoogle === undefined) delete originalWindow.google
      else originalWindow.google = originalGoogle
      if (originalWindowSetTimeout) originalWindow.setTimeout = originalWindowSetTimeout
      if (originalWindowClearTimeout) originalWindow.clearTimeout = originalWindowClearTimeout
      if (originalWindowLocation === undefined) delete originalWindow.location
      else originalWindow.location = originalWindowLocation
    }
  })

  test('existing complete script resolves immediately (no load hang)', async () => {
    const { GIS_SCRIPT_SRC, loadGoogleIdentityScript } = await import('./auth.tsx')
    if (globalThis.window) delete globalThis.window.google
    installDocument({ src: GIS_SCRIPT_SRC, readyState: 'complete' })
    const started = Date.now()
    await loadGoogleIdentityScript(8_000)
    expect(Date.now() - started).toBeLessThan(500)
  })

  test('existing complete=true script resolves immediately', async () => {
    const { GIS_SCRIPT_SRC, loadGoogleIdentityScript } = await import('./auth.tsx')
    if (globalThis.window) delete globalThis.window.google
    installDocument({ src: GIS_SCRIPT_SRC, complete: true })
    const started = Date.now()
    await loadGoogleIdentityScript(8_000)
    expect(Date.now() - started).toBeLessThan(500)
  })

  test('in-flight script without load fails soft on timeout', async () => {
    const { GIS_SCRIPT_SRC, loadGoogleIdentityScript } = await import('./auth.tsx')
    if (globalThis.window) delete globalThis.window.google
    const { listeners } = installDocument({ src: GIS_SCRIPT_SRC })
    const started = Date.now()
    await loadGoogleIdentityScript(40)
    expect(Date.now() - started).toBeLessThan(1_000)
    expect(listeners.get('load')?.length ?? 0).toBe(1)
  })

  test('already-ready GIS resolves without touching the script tag', async () => {
    const { loadGoogleIdentityScript } = await import('./auth.tsx')
    if (!globalThis.window) globalThis.window = globalThis
    globalThis.window.google = {
      accounts: {
        id: {
          initialize: () => {},
          prompt: () => {},
          renderButton: () => {},
        },
      },
    }
    const started = Date.now()
    await loadGoogleIdentityScript(8_000)
    expect(Date.now() - started).toBeLessThan(200)
  })

  test('ensureDirectAdminApiUserToken is a no-op without a direct admin-api URL', async () => {
    const { created } = installDocument()
    const { ensureDirectAdminApiUserToken } = await import('./auth.tsx')
    await ensureDirectAdminApiUserToken()
    expect(created).toEqual([])
  })

  test('One Tap skip resolves immediately as a miss (not a hang)', async () => {
    const { promptGoogleOneTap } = await import('./auth.tsx')
    if (!globalThis.window) globalThis.window = globalThis
    globalThis.window.google = {
      accounts: {
        id: {
          initialize: () => {},
          prompt: (listener) => {
            listener?.({
              isNotDisplayed: () => true,
              isSkippedMoment: () => false,
              isDismissedMoment: () => false,
            })
          },
          renderButton: () => {},
        },
      },
    }
    const started = Date.now()
    await expect(promptGoogleOneTap()).resolves.toBeNull()
    expect(Date.now() - started).toBeLessThan(500)
  })

  test('renderGoogleSignInButton mounts the official GIS button', async () => {
    const { renderGoogleSignInButton } = await import('./auth.tsx')
    if (!globalThis.window) globalThis.window = globalThis
    const rendered: Array<{ width?: number; text?: string }> = []
    globalThis.window.google = {
      accounts: {
        id: {
          initialize: () => {},
          prompt: () => {},
          renderButton: (_parent, options) => {
            rendered.push(options)
          },
        },
      },
    }
    const parent = { replaceChildren: () => {} }
    const ok = await renderGoogleSignInButton(
      parent as HTMLElement,
      'test-client.apps.googleusercontent.com',
    )
    expect(ok).toBe(true)
    expect(rendered).toEqual([
      {
        type: 'standard',
        theme: 'outline',
        size: 'large',
        text: 'signin_with',
        shape: 'rectangular',
        width: 280,
      },
    ])
  })
})

describe('Identity miss copy (P1-1 GIS vs role API)', () => {
  test('direct admin-api without a token is a Google sign-in miss', async () => {
    const { classifyIdentityMiss, GOOGLE_SIGN_IN_ERROR } = await import('./auth.tsx')
    expect(classifyIdentityMiss({ directAdminApi: true, hasUserToken: false })).toBe(
      'google_sign_in',
    )
    expect(GOOGLE_SIGN_IN_ERROR.title).toBe('Could not sign in with Google')
    expect(GOOGLE_SIGN_IN_ERROR.retryLabel).toBe('Retry')
  })

  test('direct admin-api with a token is a role-API miss (GET /me)', async () => {
    const { classifyIdentityMiss } = await import('./auth.tsx')
    expect(classifyIdentityMiss({ directAdminApi: true, hasUserToken: true })).toBe('role_api')
  })

  test('empty VITE / same-origin /api stays Cannot load role (no GIS copy)', async () => {
    const { classifyIdentityMiss, GOOGLE_SIGN_IN_ERROR } = await import('./auth.tsx')
    expect(classifyIdentityMiss({ directAdminApi: false, hasUserToken: false })).toBe('role_api')
    expect(classifyIdentityMiss({ directAdminApi: false, hasUserToken: true })).toBe('role_api')
    expect(GOOGLE_SIGN_IN_ERROR.title).not.toBe('Cannot load role')
  })
})

describe('collapsed pipeline batch row (QCQA)', () => {
  function summary(overrides: Record<string, unknown> = {}) {
    return {
      process_id: 12,
      intake_source: 'drop',
      process_at: '2026-08-21T16:00:00.000Z',
      completed_at: '2026-08-21T18:00:00.000Z',
      download_status: 'success',
      label: 'Aug 21 · CA DROP',
      linkable: true,
      overall: { percent: 100, current_stage: 'fulfillment', status: 'complete' },
      request_rows: 1_840_000,
      ...overrides,
    }
  }

  test('keeps date, status, and counts when the API returned them', async () => {
    const { collapsedBulkRowDisplay } = await importApi(undefined)
    const display = collapsedBulkRowDisplay(summary())
    expect(display.dateLabel).not.toBe('—')
    expect(display.dateLabel.length).toBeGreaterThan(0)
    expect(display.dateLabel).toContain('CA DROP')
    expect(display.sourceLabel).toBe('CA DROP')
    expect(display.statusLabel).toBe('complete')
    expect(display.progressLabel).toBe('100%')
    expect(display.countLabel).toBe('1840000 req')
  })

  test('falls back to label and download_status when process_at/overall are missing', async () => {
    const { collapsedBulkRowDisplay } = await importApi(undefined)
    const display = collapsedBulkRowDisplay(
      summary({ process_at: null, overall: undefined }),
    )
    expect(display.dateLabel).toBe('Aug 21 · CA DROP')
    expect(display.statusLabel).toBe('success')
    expect(display.progressLabel).toBe('')
    expect(display.countLabel).toBe('1840000 req')
  })

  test('QCQA fails if a returned field is blanked', async () => {
    const { collapsedBulkRowDisplay } = await importApi(undefined)
    const rows = [
      summary(),
      summary({ overall: { percent: 0, current_stage: 'download', status: 'in_progress' } }),
      summary({ process_at: 'not-a-date', overall: undefined, request_rows: 0 }),
    ]
    for (const row of rows) {
      const display = collapsedBulkRowDisplay(row)
      if (row.process_at || String(row.label ?? '').trim()) {
        expect(display.dateLabel.trim().length).toBeGreaterThan(0)
      }
      if (row.overall?.status || row.download_status) {
        expect(display.statusLabel.trim().length).toBeGreaterThan(0)
      }
      if (row.overall?.percent != null) {
        expect(display.progressLabel).toMatch(/%$/)
      }
      if (row.request_rows != null) {
        expect(display.countLabel).toContain('req')
      }
    }
  })

  test('pipeline collapsed row uses collapsedBulkRowDisplay chips', () => {
    const source = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), '..', 'routes', 'ops', 'drop-pipeline.tsx'),
      'utf8',
    )
    expect(source).toContain('collapsedBulkRowDisplay')
    expect(source).toContain('collapsed.dateLabel')
    expect(source).toContain('intake_source: row.intake_source')
    expect(source).toContain('collapsed.statusLabel')
    expect(source).toContain('collapsed.progressLabel')
    expect(source).toContain('collapsed.countLabel')
  })
})

describe('listOwnerConnectors timeout (QCQA)', () => {
  test('source sets OPS_FAST_QUERY_TIMEOUT_MS (8s SPA abort)', () => {
    const source = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), 'api.ts'),
      'utf8',
    )
    expect(source).toMatch(
      /export function listOwnerConnectors\([\s\S]*?timeoutMs:\s*OPS_FAST_QUERY_TIMEOUT_MS/,
    )
    expect(source).not.toMatch(
      /export function listOwnerConnectors\([^)]*\)\s*\{\s*return fetchAdminApi<OwnerConnectorList>\(\s*`\$\{[^`]+\}`,\s*\)/,
    )
  })
})
