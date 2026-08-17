# clients/web/

React admin UI for Legal, Operations, and Data Owners.

**Stack (locked):** Vite, React, TypeScript, TanStack Router, TanStack Query, Tailwind, Bun.

Deploy targets:

- **Dev (browser):** Cloud Run `ops-ia-web-dev` — IAP front door for **Habeas Platform** chrome
  ([`https://ops-ia-web-dev-hsa55rg7ja-uk.a.run.app`](https://ops-ia-web-dev-hsa55rg7ja-uk.a.run.app)).
  Legacy `admin-web-dev` remains for nginx-only smoke; prefer ops-ia for DROP ops + owner flows.
- **Prod path:** Firebase Hosting in front of Identity-Aware Proxy (`.firebaserc` / `firebase.json`) — not live in this repo doc.

All browser mutations go through **admin-api** only — the SPA never calls worker URLs directly.

**Agent rules:** [`AGENTS.md`](AGENTS.md)

---

## Docker

Production-like nginx image (bakes `VITE_ADMIN_API_URL` at build time):

```bash
cd clients/web
docker compose up web          # http://127.0.0.1:8080
docker compose up web-dev      # Vite hot reload on :5173
```

Override API target for local builds:

```bash
VITE_ADMIN_API_URL=https://admin-api-dev-hsa55rg7ja-uk.a.run.app docker compose up web
```

Cloud Build deploy (from repo root):

```bash
gcloud builds submit --config=infra/cloudbuild/admin-web-dev.yaml --project=example-gcp-project .
```

After first deploy, add the Cloud Run URL to `admin-api-dev` `CORS_ORIGINS` (see [`infra/README.md`](../../infra/README.md)).

---

## Local development

Terminal 1 — admin-api:

```bash
uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir app/admin_api/src
```

Terminal 2 — web (from repo root or this directory):

```bash
cd clients/web
bun install
bun run dev
```

Vite proxies `/api/*` to `http://127.0.0.1:8000` so the dashboard can call `/api/healthz` without cross-origin setup.

Optional: copy `.env.example` to `.env` and set `VITE_ADMIN_API_URL` when not using the dev proxy.

### Drop ops navigation

- **Pipeline** (`/?tab=pipeline`, also `/ops/drop-pipeline?tab=`) — **Run Pipeline** (CA DROP → download→land→promote) + bulk/individual list. Top tabs: Pipeline · Hash refresh · History · Errors · Logs. Gear / Pipeline ▾ → **Settings** opens Workers Settings (schedules, retry, fleet). Stage tabs Download / Ingest / Matching / Review / Fulfillment live inside each bulk card (`stage=`).
- **Workers** (`/ops/workers`) — fleet overview + escalations; Settings at `/ops/workers/settings`. Legacy `/ops/health*` redirects here.
- Browser never calls worker URLs — only admin-api aggregates. Local Vite → deployed admin-api-dev: run `gcloud auth application-default login`, set `VITE_PROXY_TARGET` to admin-api-dev, then `bun run dev` (Vite mints ADC Bearer ID token for super_admin); see [`AGENTS.md`](AGENTS.md).

### Vertical connectors (owner onboarding)

Owner access is **vertical assignment + IAP login** — there are **no invite URLs** and no
`/connect/{token}` redeem flow. Super_admin assigns owners to verticals under Ops
**Connections** (`/ops/connections`); assigned owners sign in through the **ops-ia-web-dev**
IAP front door and land in **Habeas Platform** chrome (welcome uses IAP `given_name`).

- **Owner wizard:** `/owner/connectors` — Mode explainer → in-wizard Live credentials + test (or
  Upload template validate) → cadence → confirm. First-login welcome routes here for the assigned
  vertical. Connecting a system does **not** by itself enable matching.
- **Ops admin:** `/ops/connections` — vertical catalog, assign owners, mode/cadence overrides,
  retest, wizard reset, delete. No invite mint, mailto, or revoke.
- **Thin client:** all writes via admin-api (`/ops/connections*`, `/ops/verticals*`, `/owner/*`);
  secrets stay in Secret Manager; UI uses `actionToast` and allowlisted test `detail` codes only.

Non–super_admin browsers: use the **ops-ia** IAP front door — not the ADC Vite proxy. Plan:
[`docs/plans/2026-08-11-001-feat-vertical-scoped-connectors-plan.md`](../../docs/plans/2026-08-11-001-feat-vertical-scoped-connectors-plan.md).

### Local DROP pipeline stack (ports)

The ops console talks only to admin-api. Admin-api proxies workers:

| Worker | Default URL | Typical local port |
|--------|-------------|--------------------|
| drop-connector | `DROP_CONNECTOR_URL` → `http://127.0.0.1:8081` | 8081 |
| drop-ingestor | `DROP_INGESTOR_URL` → `http://127.0.0.1:8082` | 8082 |
| request-dispatcher | `REQUEST_DISPATCHER_URL` → `http://127.0.0.1:8083` | 8083 |
| matching | `MATCHING_URL` → `http://127.0.0.1:8084` | 8084 |
| data-fulfillment | `DATA_FULFILLMENT_URL` → `http://127.0.0.1:8085` | 8085 |

Example (separate terminals, after `uv sync`):

```bash
uv run --package drop-connector uvicorn drop_connector.main:app --app-dir app/drop_connector/src --port 8081
uv run --package drop-ingestor uvicorn drop_ingestor.main:app --app-dir app/drop_ingestor/src --port 8082
uv run --package request-dispatcher uvicorn request_dispatcher.main:app --app-dir app/request_dispatcher/src --port 8083
uv run --package matching-worker uvicorn matching.main:app --app-dir app/matching/src --port 8084
uv run --package data-fulfillment-dispatcher uvicorn data_fulfillment_dispatcher.main:app --app-dir app/data_fulfillment_dispatcher/src --port 8085
uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir app/admin_api/src --port 8000
```

`DROP_API_KEY` stays on the connector / server env only — never in the web client.

---

## Action feedback

After you click a mutating control (save, queue, assign, decline, sync, and similar), the UI confirms the outcome with an **action toast**: a short message in the top-right corner, one supporting line, and one button such as **Retry**, **Undo**, **View**, or **Dismiss**.

That is the product standard for success, error, warning, info, and in-flight (loading → done) feedback. Designers and engineers should not introduce a different default (full-page banner, bottom snackbar, or silent success) for ordinary actions.

**Implementation:** import `actionToast` from `@/lib/action-toast` (`src/lib/action-toast.ts`). Global `Toaster` mounts in `AppShell`. Do not import `toast` from `sonner` in call sites — see [`AGENTS.md`](AGENTS.md) and [frontend-stack](../../.agent/modules/frontend-stack.md).

Toast text must not include personal data — same privacy rules as the rest of the ops UI.

---

## Scripts

| Command | Purpose |
|---------|---------|
| `bun run dev` | Dev server |
| `bun run build` | Production build to `dist/` |
| `bun run preview` | Preview production build |
| `bun run lint` | oxlint |
