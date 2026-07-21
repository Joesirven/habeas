import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'
  // Cloud Run invoker ID token (audience = admin-api URL). Mint via SA impersonation.
  const cloudRunIdToken = env.IAP_ID_TOKEN || env.CLOUD_RUN_ID_TOKEN || ''
  // Deployed admin-api has no Cloud Run IAP; identity is this header (ops-ia nginx pattern).
  const rawEmail = (env.IAP_USER_EMAIL || '').trim()
  const iapUserEmail = rawEmail
    ? rawEmail.includes(':')
      ? rawEmail
      : `accounts.google.com:${rawEmail}`
    : ''

  return {
    plugins: [react(), tailwindcss()],
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
          configure: (proxy) => {
            if (!cloudRunIdToken && !iapUserEmail) return
            proxy.on('proxyReq', (proxyReq) => {
              if (cloudRunIdToken) {
                proxyReq.setHeader('Authorization', `Bearer ${cloudRunIdToken}`)
              }
              if (iapUserEmail) {
                proxyReq.setHeader('X-Goog-Authenticated-User-Email', iapUserEmail)
              }
            })
          },
        },
      },
    },
  }
})
