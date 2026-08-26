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
| Live updates | **Server-Sent Events** — admin-api `GET /live/events` via same-origin `/api/live/events` |
| Types | Generate from admin-api OpenAPI schema |

## Realtime flow (v0)

1. Postgres `NOTIFY privacy_events` on **approval_requests** changes (and related tables as needed).
2. admin-api `LISTEN privacy_events` → forwards to Server-Sent Events clients.
3. Web `EventSource` on same-origin `/api/live/events` (EventSource cannot set Authorization) → TanStack Query `invalidateQueries` for affected resources. JSON APIs may go cross-origin; the event hop stays on `/api`.

## Admin-api access (Architecture B — intended)

admin-api is the **resource server**. Intended: humans reach the SPA through **admin-web Identity-Aware Proxy**. Browser JSON uses an in-memory Google Identity Services user ID token (`Authorization: Bearer`) when `VITE_ADMIN_API_URL` is set. Cookie IAP (`credentials: 'include'`) is not the B API session. The token is not persisted. Client id from `VITE_GOOGLE_CLIENT_ID` or `VITE_GIS_CLIENT_ID` only — never hardcode.

**Current prod web is not on B.** Live 100% is `admin-web-prod-00023-fnz` (empty-VITE / nginx `/api`). Revision **00024** is the unused B bake at **0% traffic**. Do not claim prod already uses Google Identity Services. Do not flip 00024 until GIS `/me` is proven on DEV. `allUsers` invoker is **stripped** on `admin-api-prod` / `admin-api-dev` (compute SA + `jsirven@` only). GIS JWT `aud` is the OAuth client, not the Cloud Run URL — a 00024 flip today would **403** at Cloud Run IAM.

**Server-Sent Events** always use same-origin `GET /api/live/events`. nginx or Vite `/api` proxies that hop.

- Local: leave `VITE_ADMIN_API_URL` unset → Vite proxies `/api` → `http://127.0.0.1:8000` (JSON + Server-Sent Events; no IAP).
- Local against deployed admin-api: `gcloud auth application-default login`, set
  `VITE_PROXY_TARGET` (Cloud Run URL), leave `VITE_ADMIN_API_URL` unset — Vite mints a Cloud Run ID token via ADC
  (`google-auth-library`, same audience as `habeas-cli auth login --adc`). Optional
  `IAP_USER_EMAIL` only for SA impersonation fallback. Do not paste an IAP OAuth-client
  audience token into `IAP_ID_TOKEN`.
- Cloud Build yamls bake `VITE_ADMIN_API_URL` + `VITE_GOOGLE_CLIENT_ID` into **00024** (same project brand as `IAP_OAUTH_CLIENT_ID` — not a secret). Bake ≠ cutover: `admin-web-prod.yaml` has no `--no-traffic`; 00024-at-0% is a **manual pin** to 00023. Empty `VITE_ADMIN_API_URL` is local / current-prod-00023 / rollback (all REST via `/api`).
- CLI: `habeas-cli auth login --adc` (super_admin) and `habeas-cli auth login` (IAP) — unchanged. Pin `ADMIN_API_ID_TOKEN_AUDIENCE` and `IAP_OAUTH_CLIENT_ID`.
- Do **not** re-run `infra/cloudbuild/admin-api-dev-iam.yaml` (re-enables Cloud Run IAP).
- Never call worker Cloud Run URLs from the browser.
- Do **not** edit accepted SirvenOS architecture decision records from this repo.

## Action feedback (universal)

**Canonical pattern: action toast** — shadcn/Sonner toast with title, short description, and a primary action chip (Undo / Retry / View / Open run / Dismiss). Mounted once via `Toaster` in `AppShell`. Call sites import `actionToast` from `clients/web/src/lib/action-toast.ts` — do **not** import `toast` from `sonner` directly.

| Scenario | Helper | Action chip (typical) |
|----------|--------|------------------------|
| Success | `actionToast.success` | View / Open / Dismiss |
| Error | `actionToast.error` | Retry |
| Warning | `actionToast.warning` | Keep / Undo / Dismiss |
| Info | `actionToast.info` | Details / Dismiss |
| Async / promise | `actionToast.promise` | Open run / Retry |
| Clipboard | `actionToast.copied` | Copy again |

**Do not** invent alternate feedback chrome for ordinary mutations: no page banners, inline status strips, bottom snackbars, or title-only toasts as the product default.

Privacy: toast copy must not include personally identifiable information, hashes, or DWID values — use `actionToast.safeErrorMessage` for API errors; ids/counts only where already allowed in ops UI.

## Rules

- Thin client — no business rules in browser; all authorization on admin-api.
- `/dev` labs (including `/dev/owner-map-alternatives`) ship on `admin-web-dev` only (`VITE_ENABLE_LABS=true`); `admin-web-prod` stays clean — the product wizard `/owner/connectors` may ship on prod.
- Not Next.js — single-page app on Cloud Run (`admin-web-*`) behind Identity-Aware Proxy (human SSO). Intended B API session is a Google Identity Services user Bearer. Current prod 00023 session is nginx `/api`.
- Mutations never bypass admin-api.
- After a user-triggered mutation settles, give feedback with an **action toast** (see above) — not silent success and not a one-off alert pattern.

## Search-param merge (filter clear)

When merging a filter patch into current URL search, **do not** use `patch.x !== undefined ? patch.x : current.x`. Passing `{ x: undefined }` (All / clear) is treated as “keep current,” so the filter cannot clear.

Use key presence instead:

```ts
const x = 'x' in patch ? patch.x : current.x
```

- Omit the key → preserve current value.
- Pass explicit `undefined` → clear.

Applies to Runs `buildRunsSearch`, Requests/Workers `patchSearch`, and any similar ops toolbar merge.
