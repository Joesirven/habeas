// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { plugin } from 'bun'
import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test'
import { join } from 'node:path'

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

  test('set VITE_ADMIN_API_URL without a user token omits Authorization', async () => {
    const { fetchAdminApi } = await importApi('https://admin-api-dev.example')
    await fetchAdminApi('/me')
    expect(fetchCall(fetchMock).url).toBe('https://admin-api-dev.example/me')
    expect(headerValue(fetchCall(fetchMock).init.headers, 'Authorization')).toBeNull()
  })

  test('same-origin /api never attaches Bearer even when a token is in memory', async () => {
    const { fetchAdminApi, setAdminApiUserToken } = await importApi(undefined)
    setAdminApiUserToken('must-not-be-sent')
    await fetchAdminApi('/me')
    expect(fetchCall(fetchMock).url).toBe('/api/me')
    expect(headerValue(fetchCall(fetchMock).init.headers, 'Authorization')).toBeNull()
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
