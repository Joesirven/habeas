# clients/web/

React admin UI for Legal, Operations, and Data Owners.

**Stack (locked):** Vite, React, TypeScript, TanStack Router, TanStack Query, Tailwind, Bun.

Deploy target: Firebase Hosting in front of Identity-Aware Proxy.

**Agent rules:** [`AGENTS.md`](AGENTS.md)

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

### Local DROP pipeline stack (ports)

The ops console at `/ops/drop-pipeline` talks only to admin-api. Admin-api proxies workers:

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

## Scripts

| Command | Purpose |
|---------|---------|
| `bun run dev` | Dev server |
| `bun run build` | Production build to `dist/` |
| `bun run preview` | Preview production build |
| `bun run lint` | oxlint |
