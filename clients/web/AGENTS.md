> inherits: ../../AGENTS.md

# AGENTS.md — clients/web/

**Habeas Platform** admin web (slug `habeas-cli`). Legal DROP hash/notice unchanged.

## Vocabulary (ops inbox)

**Source** = intake (**CA DROP**, portal, agent) — not a connection. **System** = a vertical’s data connection; owner verifies matching **per system**. **Test vertical** shows **System A** / **System B**; other verticals show the real name. Full list: root [`AGENTS.md`](../../AGENTS.md) and [`.agent/modules/design-taste-ops-ia.md`](../../.agent/modules/design-taste-ops-ia.md).

## Locked stack

Vite · React · TypeScript · TanStack Router · TanStack Query · shadcn · Bun

Labs (`/dev/*`) are DEV-only — Cloud Build sets `VITE_ENABLE_LABS=true` on `admin-web-dev` and `false` on `admin-web-prod` / `admin-web-qa`.

Deployed front doors (all IAP SSO): `admin-web-dev` (labs on → admin-api-dev), `admin-web-prod` (labs off → admin-api-prod), `admin-web-qa` (`https://admin-web-qa-hsa55rg7ja-uk.a.run.app`, labs off, prod-shaped **QA** link deliberately wired to **admin-api-dev** so testers cannot write prod — never repoint it at admin-api-prod).

## Identity (Architecture B)

admin-api is the **resource server**. **Prod web is Architecture B:** Cloud Build bakes `VITE_ADMIN_API_URL` → `admin-api-prod`. Humans reach the SPA through **admin-web Identity-Aware Proxy** (Workspace SSO — page access only). Browser JSON calls admin-api cross-origin with an in-memory **Google Identity Services** user ID token (`Authorization: Bearer`). Cookie IAP (`credentials: 'include'`) is not the B API session. The token is not persisted.

Client id comes from `VITE_GOOGLE_CLIENT_ID` (Google Secret Manager `iap-oauth-client-id` at Cloud Build submit) or `VITE_GIS_CLIENT_ID` — never hardcode.

**Server-Sent Events** stay same-origin `GET /api/live/events` (EventSource cannot set Authorization). nginx or Vite `/api` proxies that hop to admin-api `GET /live/events`. Empty `VITE_ADMIN_API_URL` remains local + rollback (all REST via `/api`). Do not move the event bus off admin-api.

`admin-api-prod` IAM matches live `admin-api-dev` (`allUsers` + compute SA + `jsirven@`) so Cloud Run IAM does not 403 GIS; the app verifies the JWT. Do not pin `admin-web-prod` to numbered revisions (00023 / 00024).

CLI Application Default Credentials (`habeas-cli auth login --adc`) and IAP login (`habeas-cli auth login`) stay unchanged. Do **not** re-run `infra/cloudbuild/admin-api-dev-iam.yaml` (re-enables Cloud Run IAP). Do **not** edit accepted SirvenOS architecture decision records from this repo.


## Realtime

Connect to admin-api `GET /live/events` via same-origin `/api/live/events` (Server-Sent Events). Invalidate TanStack Query cache on `privacy_events` payloads.

## Navigation (Ops IA — Request / Job / Run)

- **Requests** → list (row opens **detail workbench** — no journey strip on rows), Needs attention, SLAs (shell), Conditions (Legal), Upload.
- **Ops** (super_admin): **Pipeline** nav (`/?tab=` — Pipeline · Hash refresh · History · Errors · Logs; no Dashboard home, no Configurations tab), Workers (overview + escalations; **Settings** for fleet/schedules/retry), Runs, Connections (`/ops/connections`). Legacy `/ops/health` and `?tab=configurations` redirect to Workers / Settings.
- Browser never calls worker URLs — only admin-api aggregates.
- Pipeline **Errors** / **Logs** share one explorer (`GET /ops/logs`); Errors locks severity to ERROR (severity filtered in SQL so ERROR is not drowned by INFO audits).
- **Workers Settings** (`/ops/workers/settings`, Pipeline ▾ → Settings, console gear): fleet health (`GET /ops/workers/fleet`), Cloud Scheduler schedules, retry floors, attempt-table browser. Single edit surface — do not reintroduce a Pipeline Configurations tab.
- Vertical connectors (shipped): super_admin `/ops/connections` — vertical catalog, assign
  owners, mode/cadence, retest, delete. Owners `/owner/connectors` wizard (Mode explainer,
  in-wizard Live creds+test, Upload templates). **Connection owner invites** stay 410
  (assignment is the grant). **`data_user` teammate invites are not live** —
  handlers exist (`POST /owner/verticals/{id}/member-invites`,
  `GET/POST /connect/$token`) but `owner_router` is not mounted on admin-api.
  Owner Connectors Team members UI must not be described as shipped.
- `/me`: `given_name`, `needs_connector_setup`, `assigned_vertical_labels`,
  `connector_reminders` (soft — never block login).
- Matching hard-gated on stale upload / rotation overdue / wizard incomplete; surfaces
  **Needs refresh** / **Action required** (R52 on matching views). Connecting ≠ matching.
  Owner-system people search uses the same gate (`resolveMatchingConnectorGate`).
- Matching inventory (code-backed; do not invent APIs or routes):
  - **Live:** `data`, `auth0`
  - **Catalog-only / not live:** Axios HQ (`axios_hq`), Lever, Paylocity, Cassandra
  - Copy: catalog-only / not live — never “coming soon”
- Results lab (`/requests/matching-results-lab`): ops queue is landed
  `GET /ops/drop/matching-results` (ids/counts). Add-person search by vertical:
  `data` → MDR `GET /ops/drop/matching-contacts/search` (view-only — no owner
  cadence gate); `auth0` → `GET /requests/{id}/verticals/auth0/match-candidates`;
  catalog-only → **Needs connection** (search disabled).
- `data` vertical view-only in owner wizard. Cassandra = infra card only.
- First-login welcome + skippable tour (`localStorage`, `habeas-cli.tour.v1.*`). Secrets
  only in Secret Manager; `actionToast` + allowlisted test `detail` codes. Plan:
  `docs/plans/2026-08-11-001-feat-vertical-scoped-connectors-plan.md`.
- **Planned consolidation** (requirements-only): command-center Home + hybrid Inbox — `docs/plans/2026-07-30-005-feat-ops-command-center-ia-plan.md` (not shipped yet).

## Ops density (Prefect / Dagster feel)

Keep Habeas Amigo/`taste-*` tokens (navy, frost chips, matte panels). On **Runs, Requests, Ops dashboard, request journey**:

- Table-first / rail-first composition — not landing-page heroes.
- Compact rows (`text-xs`, tight `py`), status tabs/filters, URL search params.
- Search-param merges: use `'key' in patch` (not `!== undefined`) so All/clear can pass `undefined` — see frontend-stack.
- Request journey: **four-stage detail-only rail** (Ingest → Matching → Fulfillment → Notice) with per-vertical Matching/Fulfillment clusters; batch selection = aggregate workbench. Dense run list like Dagster Runs.
- One volume strip/chart on ops dashboard (Prefect overview) — not four equal marketing KPI tiles as the whole page.
- Do **not** invent a second design system or copy Prefect dark/purple chrome.

Ops visual system: [`.agent/modules/design-taste-ops-ia.md`](../../.agent/modules/design-taste-ops-ia.md) (`habeas-ops-amigo-prefect-dagster`).  
General Amigo frost: [`.agent/modules/design-taste.md`](../../.agent/modules/design-taste.md).

## DROP pipeline

- Top tabs: Pipeline · Hash refresh · History · Errors · Logs (`tab=`). **Run Pipeline** (CA DROP) queues download → land → promote; confirm dialog must stay `fixed` (never pass `relative` into `DialogContent` — twMerge would park it at page bottom). Gear → Workers Settings.
- Errors / Logs: shared project log explorer (`GET /ops/logs`); Errors = ERROR severity only.
- Schedules / retry / fleet: **Workers → Settings** only (not a Pipeline tab).
- Stage tabs Download / Ingest / Matching / Review / Fulfillment live inside each bulk card (`stage=`); Land+Promote combined as Ingest — not top console tabs.
- Bulk cards: compact collapsed row (Dur/Prog + tiny stage chips); Matching completion % from `matching_attempts` only (do not blend review); Review tab uses `stages.review`; **Matching results** when Review stage is selected.
- Bulk-card state tiles → `/ops/runs?process=<id>&job=…&status=…&window=…` (`process` = download attempt id; API query `process_id`).
- Individual view: status toggles (Open & failed / Queued / Failed / Abandoned / Finished / All) on the same filter row as Intake/Window.
- Hash-index: **Refresh state** / **Refresh all** enqueue then process in one action (USPS 50+DC); rematch-on-refresh for every successful state.
- Matching review / fulfill-decline live in Inbox (`?bulk=`). Bulk card runs support pagination, re-run, assign, detail dialog. Journey workbench chrome + Legal kickoff / Access identity gates: [`.agent/modules/design-taste-ops-ia.md`](../../.agent/modules/design-taste-ops-ia.md).

## Local admin-api proxy

Local ADC proxy is **unchanged** (same as CLI `auth login --adc`). Leave `VITE_ADMIN_API_URL` unset so JSON and Server-Sent Events both use `/api` — local / rollback path, not the prod Architecture B GIS session.
- Default: `VITE_PROXY_TARGET=http://127.0.0.1:8000` (no Identity-Aware Proxy).
- Deployed admin-api-dev (`*.run.app`): Vite mints a Cloud Run ID token via Application
  Default Credentials (`google-auth-library` `getIdTokenClient`, audience = service origin).
  Setup: `gcloud auth application-default login`, then `bun run dev` with `VITE_PROXY_TARGET`.
  ADC JWT email alone grants super_admin when on `ADMIN_API_SUPER_ADMINS` (no IAP header).
  Optional `IAP_USER_EMAIL` only for SA impersonation fallback when ADC mint fails.
  Precedence: static `CLOUD_RUN_ID_TOKEN` / `IAP_ID_TOKEN` (correct aud) → ADC → gcloud SA impersonation.
- Do not put an IAP OAuth-client audience token in `IAP_ID_TOKEN` — admin-api will 401.
- Non-super_admin: use **admin-web-dev** (IAP), not the local proxy.
- Super_admin can simulate effective role via banner `View as` → `X-Dev-Simulate-Role` (sessionStorage).

## Action feedback

**Universal pattern: action toast** via `actionToast` from `@/lib/action-toast` (Sonner under the hood). After mutations: title + description + one action chip (Retry / Undo / View / Dismiss). Global `Toaster` in `AppShell`. Do not add snackbars, page banners, or title-only toasts as defaults. Do not import `toast` from `sonner` in call sites. Full rules → [frontend-stack](../../.agent/modules/frontend-stack.md) · visual → [design-taste](../../.agent/modules/design-taste.md).

## Rules

- Thin client — no business rules in browser; all authorization on admin-api.
- Generate TypeScript types from admin-api OpenAPI.
- Not Next.js.
- No PII/hashes/dwids in UI payloads beyond existing ops id/count rules (includes toast copy).
- Mutation outcomes → `actionToast`.

Full detail → [`.agent/modules/frontend-stack.md`](../../.agent/modules/frontend-stack.md).
