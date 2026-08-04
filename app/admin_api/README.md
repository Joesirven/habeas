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

## Local

```bash
uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir app/admin_api/src
```

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
