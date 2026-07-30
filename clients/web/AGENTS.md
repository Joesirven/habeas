> inherits: ../../AGENTS.md

# AGENTS.md — clients/web/

Admin web single-page application.

## Locked stack

Vite · React · TypeScript · TanStack Router · TanStack Query · shadcn · Bun

## Realtime

Connect to admin-api `GET /live/events` (Server-Sent Events). Invalidate TanStack Query cache on `privacy_events` payloads.

## Navigation (Ops IA — Request / Job / Run)

- **Requests** → list (row opens **detail workbench** — no journey strip on rows), Needs attention, SLAs (shell), Conditions (Legal), Upload.
- **Ops** (super_admin): Dashboard (Pipeline · Hash refresh · History · Errors · Logs · Configurations), Workers, Runs, Jobs (shell), Insights (`/ops/health`), Incidents (shell → failed Runs), Connections (`/ops/connections`).
- **Console** (super_admin): `/ops/drop-pipeline?tab=` mutation power surface (same tab set as Dashboard).
- Browser never calls worker URLs — only admin-api aggregates.
- Dashboard **Errors** / **Logs** share one explorer (`GET /ops/logs`); Errors locks severity to ERROR.
- Connections onboarding: Ops list/invite/test + public redeem route `/connect/$token` (no IAP; one-time invite).
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

- Top tabs: Pipeline · Hash refresh · History · Errors · Logs · Configurations (`tab=`). **Run Pipeline** (CA DROP) queues download → land → promote.
- Errors / Logs: shared project log explorer (`GET /ops/logs`); Errors = ERROR severity only.
- Stage tabs Download / Ingest / Matching / Review / Fulfillment live inside each bulk card (`stage=`); Land+Promote combined as Ingest — not top console tabs.
- Bulk cards: compact collapsed row (Dur/Prog + tiny stage chips); Matching completion % from `matching_attempts` only (do not blend review); Review tab uses `stages.review`; **Matching results** when Review stage is selected.
- Bulk-card state tiles → `/ops/runs?process=<id>&job=…&status=…&window=…` (`process` = download attempt id; API query `process_id`).
- Individual view: status toggles (Open & failed / Queued / Failed / Abandoned / Finished / All) on the same filter row as Intake/Window.
- Hash-index: **Refresh state** / **Refresh all** enqueue then process in one action (USPS 50+DC); rematch-on-refresh for every successful state.
- Matching review / fulfill-decline live in Inbox (`?bulk=`). Bulk card runs support pagination, re-run, assign, detail dialog. Journey workbench chrome + Legal kickoff / Access identity gates: [`.agent/modules/design-taste-ops-ia.md`](../../.agent/modules/design-taste-ops-ia.md).

## Local admin-api proxy

- Default: `VITE_PROXY_TARGET=http://127.0.0.1:8000` (no Identity-Aware Proxy).
- Deployed admin-api-dev (`*.run.app`): Vite mints a Cloud Run ID token via Application
  Default Credentials (`google-auth-library` `getIdTokenClient`, audience = service origin).
  Setup: `gcloud auth application-default login`, then `bun run dev` with `VITE_PROXY_TARGET`.
  ADC JWT email alone grants super_admin when on `ADMIN_API_SUPER_ADMINS` (no IAP header).
  Optional `IAP_USER_EMAIL` only for SA impersonation fallback when ADC mint fails.
  Precedence: static `CLOUD_RUN_ID_TOKEN` / `IAP_ID_TOKEN` (correct aud) → ADC → gcloud SA impersonation.
- Do not put an IAP OAuth-client audience token in `IAP_ID_TOKEN` — admin-api will 401.
- Non-super_admin: use ops-ia IAP front door, not the local proxy.
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
