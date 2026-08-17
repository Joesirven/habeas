# Admin API

Main control-plane FastAPI app. Identity-Aware Proxy, dashboard, approvals, Server-Sent Events
live stream, mutation routes for web and Habeas CLI.

## DROP ops (Wave B)

| Surface | Endpoints (representative) |
|---------|----------------------------|
| Pipeline status / spine proxies | `GET /ops/drop/pipeline`, download/land/promote/dispatch/match/fulfill proxies |
| Hash-index refresh | `POST .../hash-index-refresh/enqueue`, `.../enqueue-all`, `.../process` |
| Matching results | list/detail (attempt history + allowlisted `audit_payload`), promote/decline (individual + bulk) |
| Assign / escalate | `POST /ops/drop/workflow/assign`, `.../escalate`, `GET .../assignments` |
| Health / fleet | `GET /ops/workers/fleet`, `GET /ops/drop/workers`, `GET /ops/health/queues`, `GET/PATCH /ops/health/retry-config`, `GET|PATCH /ops/workers/schedules`, attempt-table browser under `/ops/workers/attempt-tables*` |
| Home summary | `GET /ops/drop/stats/global` |

Browser never calls workers — admin_api aggregates `/readyz` + Postgres queue depths.

## Vertical connectors

Owner onboarding is **vertical assignment + IAP login** — not invite links. Super_admin assigns
owners via `/ops/verticals/assignments`; owners complete setup in the `/owner/connectors` wizard
(Mode → in-wizard connect+test → cadence → confirm). Invite mint/redeem (`/connect/{token}`) is
retired.

| Surface | Endpoints (representative) |
|---------|----------------------------|
| Vertical catalog + assignments | `GET/POST/DELETE /ops/verticals`, `GET/POST/DELETE /ops/verticals/assignments`, bindings |
| Ops connections admin | `GET/POST/DELETE /ops/connections`, `POST .../test`, `POST .../wizard/reset` |
| Owner wizard | `GET/POST /owner/verticals/{id}/systems/{system}/*` (mode, credentials, upload, test, wizard complete) |
| Session | `GET /me` — `given_name`, `assigned_vertical_labels`, `needs_connector_setup`, `connector_reminders` |

Secrets write to Secret Manager only (`dpra/connections/{system}/{connection_id}`). Connection
tests return allowlisted `detail` codes — never echo credentials. All mutations are IAP-gated on
deployed admin-api; browser reaches admin-api through the ops-ia IAP front door or CLI auth.

Plan: [`docs/plans/2026-08-11-001-feat-vertical-scoped-connectors-plan.md`](../../docs/plans/2026-08-11-001-feat-vertical-scoped-connectors-plan.md).

## Local

```bash
uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir app/admin_api/src
```

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
