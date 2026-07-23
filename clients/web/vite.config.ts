import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { defineConfig, loadEnv, type Plugin } from 'vite'
import { fileURLToPath, URL } from 'node:url'

const execFileAsync = promisify(execFile)

const DEFAULT_IMPERSONATE_SA =
  '95660886550-compute@developer.gserviceaccount.com'

function isCloudRunTarget(target: string): boolean {
  try {
    return new URL(target).hostname.endsWith('.run.app')
  } catch {
    return false
  }
}

/** Audience = origin of proxy target (scheme + host, no path). */
function audienceFromTarget(target: string): string {
  const url = new URL(target)
  return `${url.protocol}//${url.host}`
}

function jwtExpiryMs(token: string): number {
  try {
    const payload = token.split('.')[1]
    if (!payload) return Date.now() + 3_600_000
    const json = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8')) as {
      exp?: number
      aud?: string | string[]
    }
    return typeof json.exp === 'number' ? json.exp * 1000 : Date.now() + 3_600_000
  } catch {
    return Date.now() + 3_600_000
  }
}

function jwtAudience(token: string): string | null {
  try {
    const payload = token.split('.')[1]
    if (!payload) return null
    const json = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8')) as {
      aud?: string | string[]
    }
    if (typeof json.aud === 'string') return json.aud
    if (Array.isArray(json.aud) && typeof json.aud[0] === 'string') return json.aud[0]
    return null
  } catch {
    return null
  }
}

function normalizeIapEmail(raw: string): string {
  const trimmed = raw.trim()
  if (!trimmed) return ''
  return trimmed.includes(':') ? trimmed : `accounts.google.com:${trimmed}`
}

/**
 * User ADC cannot mint Cloud Run ``--audiences`` ID tokens. Mirror the CLI:
 * impersonate the admin-api runtime SA and include email.
 */
function createImpersonatedIdTokenCache(audience: string, impersonateSa: string) {
  let cached: { token: string; expiresAt: number } | null = null
  let inflight: Promise<string> | null = null

  return async function getIdToken(): Promise<string> {
    const skewMs = 60_000
    if (cached && Date.now() < cached.expiresAt - skewMs) {
      return cached.token
    }
    if (!inflight) {
      inflight = (async () => {
        const { stdout, stderr } = await execFileAsync(
          'gcloud',
          [
            'auth',
            'print-identity-token',
            `--audiences=${audience}`,
            `--impersonate-service-account=${impersonateSa}`,
            '--include-email',
          ],
          { timeout: 30_000, maxBuffer: 1024 * 1024 },
        )
        const token = stdout.trim()
        if (!token) {
          throw new Error(
            `gcloud returned empty identity token${stderr ? `: ${stderr.trim()}` : ''}`,
          )
        }
        cached = { token, expiresAt: jwtExpiryMs(token) }
        return token
      })().finally(() => {
        inflight = null
      })
    }
    return inflight
  }
}

/**
 * Inject Cloud Run invoker Authorization + actor email before Vite's /api proxy.
 * Browser headers such as X-Dev-Simulate-Role pass through unchanged.
 */
function adcProxyAuthPlugin(options: {
  audience: string
  staticToken: string
  impersonateSa: string
  iapUserEmail: string
}): Plugin {
  const staticAudOk =
    Boolean(options.staticToken) &&
    Boolean(options.audience) &&
    jwtAudience(options.staticToken) === options.audience

  // Prefer a correct static Cloud Run token; otherwise mint via SA impersonation.
  // Ignore wrong-audience static tokens (common: IAP OAuth client aud pasted into IAP_ID_TOKEN).
  const getImpersonatedToken =
    options.audience && options.impersonateSa && !staticAudOk
      ? createImpersonatedIdTokenCache(options.audience, options.impersonateSa)
      : null

  const injectAuth = Boolean(getImpersonatedToken) || staticAudOk

  return {
    name: 'adc-proxy-auth',
    configureServer(server) {
      if (!injectAuth) return

      server.middlewares.use(async (req, res, next) => {
        if (!req.url?.startsWith('/api')) {
          next()
          return
        }
        try {
          if (staticAudOk) {
            req.headers.authorization = `Bearer ${options.staticToken}`
          } else if (getImpersonatedToken) {
            const token = await getImpersonatedToken()
            req.headers.authorization = `Bearer ${token}`
          }
          // SA Bearer needs the user email header for allowlists (CLI auth login pattern).
          if (options.iapUserEmail) {
            req.headers['x-goog-authenticated-user-email'] = options.iapUserEmail
          }
          next()
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err)
          res.statusCode = 502
          res.setHeader('Content-Type', 'text/plain; charset=utf-8')
          res.end(
            `Failed to mint Cloud Run ID token for ${options.audience}: ${message}\n` +
              'Ensure gcloud auth login, permission to impersonate ' +
              `${options.impersonateSa}, and IAP_USER_EMAIL is set to your @habeas.us address.\n`,
          )
        }
      })
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'
  const staticToken = (env.IAP_ID_TOKEN || env.CLOUD_RUN_ID_TOKEN || '').trim()
  const impersonateSa = (
    env.IAP_IMPERSONATE_SERVICE_ACCOUNT || DEFAULT_IMPERSONATE_SA
  ).trim()
  const iapUserEmail = normalizeIapEmail(env.IAP_USER_EMAIL || '')
  const cloudRun = isCloudRunTarget(proxyTarget)
  const audience = cloudRun ? audienceFromTarget(proxyTarget) : ''

  return {
    plugins: [
      ...(cloudRun
        ? [
            adcProxyAuthPlugin({
              audience,
              staticToken,
              impersonateSa,
              iapUserEmail,
            }),
          ]
        : []),
      react(),
      tailwindcss(),
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          secure: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
