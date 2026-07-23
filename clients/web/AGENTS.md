> inherits: ../../AGENTS.md

# AGENTS.md — clients/web/

Admin web single-page application.

## Locked stack

Vite · React · TypeScript · TanStack Router · TanStack Query · shadcn · Bun

## Realtime

Connect to admin-api `GET /live/events` (Server-Sent Events). Invalidate TanStack Query cache on `privacy_events` payloads.

## Navigation (Ops IA — Request / Job / Run)

- **Requests** → list (row opens journey), Needs attention, SLAs (shell).
- **Ops** (super_admin): Dashboard (Pipeline · Hash refresh · History · Configurations), Workers, Runs, Jobs (shell), Insights (`/ops/health`), Incidents (shell → failed Runs).
- **Console** (super_admin): `/ops/drop-pipeline?tab=` mutation power surface (same tab set as Dashboard).
- Browser never calls worker URLs — only admin-api aggregates.

## Ops density (Prefect / Dagster feel)

Keep Habeas Amigo/`taste-*` tokens (navy, frost chips, matte panels). On **Runs, Requests, Ops dashboard, request journey**:

- Table-first / rail-first composition — not landing-page heroes.
- Compact rows (`text-xs`, tight `py`), status tabs/filters, URL search params.
- Search-param merges: use `'key' in patch` (not `!== undefined`) so All/clear can pass `undefined` — see frontend-stack.
- Horizontal stage rail for request journey; dense run list like Dagster Runs.
- One volume strip/chart on ops dashboard (Prefect overview) — not four equal marketing KPI tiles as the whole page.
- Do **not** invent a second design system or copy Prefect dark/purple chrome.

Ops visual system: [`.agent/modules/design-taste-ops-ia.md`](../../.agent/modules/design-taste-ops-ia.md) (`habeas-ops-amigo-prefect-dagster`).  
General Amigo frost: [`.agent/modules/design-taste.md`](../../.agent/modules/design-taste.md).

## DROP pipeline

- Top tabs: Pipeline · Hash refresh · History · Configurations (`tab=`). **Run Pipeline** (CA DROP) queues download → land → promote.
- Stage tabs Download / Ingest / Matching / Fulfillment live inside each bulk card (`stage=`); Land+Promote combined as Ingest — not top console tabs.
- Bulk cards: compact collapsed row (Dur/Prog + tiny stage chips); Matching completion % from `matching_attempts` only (do not blend review); **Matching results** only when Matching stage is selected.
- Bulk-card state tiles → `/ops/runs?process=<id>&job=…&status=…&window=…` (`process` = download attempt id; API query `process_id`).
- Individual view: status toggles (Open & failed / Queued / Failed / Abandoned / Finished / All) on the same filter row as Intake/Window.
- Hash-index: **Refresh state** / **Refresh all** enqueue then process in one action (USPS 50+DC); rematch-on-refresh for every successful state.
- Matching review / fulfill-decline live in Inbox (`?bulk=`). Bulk card runs support pagination, re-run, assign, detail dialog.

## Local admin-api proxy

- Default: `VITE_PROXY_TARGET=http://127.0.0.1:8000` (no Identity-Aware Proxy).
- Deployed admin-api-dev (`*.run.app`): Vite impersonates the admin-api runtime SA via
  `gcloud auth print-identity-token --audiences=<service> --impersonate-service-account=…`
  (user ADC cannot mint Cloud Run audiences). Injects `Authorization: Bearer` +
  `X-Goog-Authenticated-User-Email` from `IAP_USER_EMAIL`. Requires
  `IAP_IMPERSONATE_SERVICE_ACCOUNT` (defaults to project compute SA).
- Do not put an IAP OAuth-client audience token in `IAP_ID_TOKEN` — admin-api will 401.
- Non-super_admin: use ops-ia IAP front door, not the local proxy.
- Super_admin can simulate effective role via banner `View as` → `X-Dev-Simulate-Role` (sessionStorage).

## Rules

- Thin client — no business rules in browser; all authorization on admin-api.
- Generate TypeScript types from admin-api OpenAPI.
- Not Next.js.
- No PII/hashes/dwids in UI payloads beyond existing ops id/count rules.

Full detail → [`.agent/modules/frontend-stack.md`](../../.agent/modules/frontend-stack.md).
