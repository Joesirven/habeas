import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { GoogleAuth } from 'google-auth-library'
import { defineConfig, loadEnv, type Plugin } from 'vite'
import { fileURLToPath, URL } from 'node:url'

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
    }
    return typeof json.exp === 'number' ? json.exp * 1000 : Date.now() + 3_600_000
  } catch {
    return Date.now() + 3_600_000
  }
}

function createAdcIdTokenCache(audience: string) {
  let cached: { token: string; expiresAt: number } | null = null
  let inflight: Promise<string> | null = null
  const auth = new GoogleAuth()

  return async function getIdToken(): Promise<string> {
    const skewMs = 60_000
    if (cached && Date.now() < cached.expiresAt - skewMs) {
      return cached.token
    }
    if (!inflight) {
      inflight = (async () => {
        const client = await auth.getIdTokenClient(audience)
        const token = await client.idTokenProvider.fetchIdToken(audience)
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
 * Inject Cloud Run invoker Authorization (ADC-minted or static env override) before
 * Vite's /api proxy. Browser headers such as X-Dev-Simulate-Role pass through unchanged.
 */
function adcProxyAuthPlugin(options: {
  useAdc: boolean
  audience: string
  staticToken: string
  /** Only set when VITE_UNSAFE_IAP_USER_EMAIL=1 — spoofable; omit on ADC path. */
  iapUserEmail: string
}): Plugin {
  const getAdcToken = options.useAdc ? createAdcIdTokenCache(options.audience) : null
  const hasBearer = Boolean(options.staticToken || getAdcToken)
  const injectAuth = hasBearer || Boolean(options.iapUserEmail)

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
          if (options.staticToken) {
            req.headers.authorization = `Bearer ${options.staticToken}`
          } else if (getAdcToken) {
            const token = await getAdcToken()
            req.headers.authorization = `Bearer ${token}`
          }
          // Never attach spoofable IAP email alongside ADC/static Bearer — admin-api
          // would treat matching/disagreeing headers specially; JWT email is identity.
          if (options.iapUserEmail && !hasBearer) {
            req.headers['x-goog-authenticated-user-email'] = options.iapUserEmail
          }
          next()
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err)
          res.statusCode = 502
          res.setHeader('Content-Type', 'text/plain; charset=utf-8')
          res.end(
            `Failed to mint ADC ID token for ${options.audience}: ${message}\n` +
              'Ensure Application Default Credentials (gcloud auth application-default login) ' +
              'and that this principal is in SUPER_ADMINS on admin-api-dev.\n',
          )
        }
      })
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'
  // Optional override: skip ADC minting when a pre-minted token is provided.
  const staticToken = (env.IAP_ID_TOKEN || env.CLOUD_RUN_ID_TOKEN || '').trim()
  // Spoofable header — only when explicitly opted in AND not using Bearer ADC.
  const unsafeIapEmail = env.VITE_UNSAFE_IAP_USER_EMAIL === '1'
  const rawEmail = unsafeIapEmail ? (env.IAP_USER_EMAIL || '').trim() : ''
  const iapUserEmail = rawEmail
    ? rawEmail.includes(':')
      ? rawEmail
      : `accounts.google.com:${rawEmail}`
    : ''
  const cloudRun = isCloudRunTarget(proxyTarget)
  const audience = cloudRun ? audienceFromTarget(proxyTarget) : ''

  return {
    plugins: [
      adcProxyAuthPlugin({
        useAdc: cloudRun && !staticToken,
        audience,
        staticToken,
        iapUserEmail,
      }),
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
