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

## Per-vertical dispositions

`request_vertical_dispositions` is the source of record for the gates fulfillment reads.

| Surface | Endpoints |
|---------|-----------|
| List | `GET /requests/{request_id}/dispositions` |
| Upsert | `PUT /requests/{request_id}/dispositions/{vertical}` (`status` 3/4/5, `dwids`, `vendor_record_ids`, `early_advance`) |

Live verticals are `data` and `auth0`. Axios HQ (`axios_hq`), Lever, Paylocity, and Cassandra are catalog-only and rejected on write. Mailchimp is retired. Status 3/4 require a selection (`dwids` for `data`, defaulting to the matching result; `vendor_record_ids` for `auth0`); status 5 requires none. Matching promote upserts the `data` disposition and keeps `drop_raw_requests.response_status` in sync. Selected ids reach authorized callers only — audit records counts.

## Auth0 vertical

Confirm-only owner search on **dev**: matching-dev writes `request_vertical_matching`; this API returns opaque `vendor_record_id`s and accepts Auth0 dispositions. Auth0 is live alongside `data`.

**Cadence is UNSET and out of scope.** These routes do **not** call `evaluate_connection_gate`, persist `refresh_policy`, or stamp `last_successful_refresh_at`. Matching runs with unset cadence.

**`auth0-dev` is not deployed.** Hash-refresh **process** proxies to `AUTH0_WORKER_URL` (default `http://127.0.0.1:8080`) — local uvicorn only. Do not set a fabricated `*.run.app` Auth0 URL. Enqueue against admin-api-dev still writes Postgres; process on that service cannot reach a laptop worker — curl `http://127.0.0.1:8080/hash-refresh/process` after enqueue. Worker runbook: [`app/auth0/README.md`](../auth0/README.md) § Auth0 matching on dev. matching-dev IAM: [`infra/README.md`](../../infra/README.md).

| Surface | Endpoints | Role |
|---------|-----------|------|
| Hash refresh (mart prerequisite) | `POST /ops/verticals/auth0/hash-refresh/enqueue`, `POST .../process` | `super_admin` |
| Match candidates | `GET /requests/{request_id}/verticals/auth0/match-candidates` | `data_owner`, `admin`, `legal`, `super_admin` |
| Lab probe | `GET .../match-candidates/status` | same |
| Confirm | `PUT /requests/{request_id}/dispositions/auth0` | same as other dispositions |
| Matching-results detail | `GET /ops/drop/matching-results/{request_id}` includes `auth0_vertical` | matching-results readers |

| Variable | Role |
|----------|------|
| `AUTH0_WORKER_URL` | Process proxy target (default `http://127.0.0.1:8080`) |

There is **no** Habeas CLI wrapper for Auth0 hash refresh (`habeas-cli drop hash-index-refresh` is DROP only).

Candidates: `{ match_count, candidates: [{ vendor_record_id }] }` from the snapshot; if missing, derive the request email hash and read the mart (read-only). Audit arguments: request id + counts — no email or hash. Status probe: `{ snapshot_present, match_count }`.

Disposition body may include `vendor_record_ids`. Status 3/4 require ≥1 vendor id; status 5 requires none. Auth0 does **not** sync `drop_raw_requests.response_status`. Audit: `selected_vendor_record_id_count` only.

Numbered dev path: (1) hash-refresh enqueue / process, (2) DROP dispatch / ensure-drain on matching-dev, (3) verify `request_vertical_matching`, (4) GET candidates + PUT disposition. See [`app/matching/README.md`](../matching/README.md) § Auth0 vertical.

Remaining-ops routes `/ops/verticals/axios_headquarters/*` (and paylocity / lever /
sheets) exist on this tree. First Cloud Run for those workers is Jose-gated. Do not
create `app/axios_headquarters` here — that worker lives in another checkout. Worker
URLs are settings-only; do not invent `*.run.app` hosts.


## Local

```bash
uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir app/admin_api/src
```

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
