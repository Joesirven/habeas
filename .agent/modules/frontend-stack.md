# module: frontend-stack

> Gate: editing `clients/web/`.

Visual design: load [`design-taste.md`](design-taste.md). For DROP Ops IA (Runs / Requests / ops dashboard / journey), also load [`design-taste-ops-ia.md`](design-taste-ops-ia.md).

## Locked stack

| Piece | Choice |
|-------|--------|
| Build | Vite |
| UI | React, TypeScript, Tailwind, shadcn/ui |
| Package manager | Bun |
| Routing | **TanStack Router** |
| Server state | **TanStack Query** |
| Live updates | **Server-Sent Events** — `GET /live/events` on admin-api |
| Types | Generate from admin-api OpenAPI schema |

## Realtime flow (v0)

1. Postgres `NOTIFY privacy_events` on **approval_requests** changes (and related tables as needed).
2. admin-api `LISTEN privacy_events` → forwards to Server-Sent Events clients.
3. Web `EventSource` → TanStack Query `invalidateQueries` for affected resources.

## Admin-api access (Identity-Aware Proxy)

- Local: leave `VITE_ADMIN_API_URL` unset → Vite proxies `/api` → `http://127.0.0.1:8000` (no IAP).
- Local against deployed admin-api: `gcloud auth application-default login`, set
  `VITE_PROXY_TARGET` (Cloud Run URL) — Vite mints a Cloud Run ID token via ADC
  (`google-auth-library`, same audience as `habeas-cli auth login --adc`). Optional
  `IAP_USER_EMAIL` only for SA impersonation fallback. Do not paste an IAP OAuth-client
  audience token into `IAP_ID_TOKEN`.
- Deployed SPA may set `VITE_ADMIN_API_URL` to admin-api; `fetch` uses `credentials: 'include'` for IAP cookies. Cross-origin IAP is best-effort — use CLI for reliable mutations.
- Never call worker Cloud Run URLs from the browser.

## Rules

- Thin client — no business rules in browser; all authorization on admin-api.
- Not Next.js — single-page app on Cloud Run (`admin-web-*`) behind Identity-Aware Proxy.
- Mutations never bypass admin-api.

## Search-param merge (filter clear)

When merging a filter patch into current URL search, **do not** use `patch.x !== undefined ? patch.x : current.x`. Passing `{ x: undefined }` (All / clear) is treated as “keep current,” so the filter cannot clear.

Use key presence instead:

```ts
const x = 'x' in patch ? patch.x : current.x
```

- Omit the key → preserve current value.
- Pass explicit `undefined` → clear.

Applies to Runs `buildRunsSearch`, Requests/Workers `patchSearch`, and any similar ops toolbar merge.
