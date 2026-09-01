# Admin API

Main control-plane FastAPI app. **Resource server** for web, CLI, and future clients.
Dashboard, approvals, Server-Sent Events live stream, mutation routes.

Cloud Run IAP is **off** (`--no-iap`). Deployed identity is app-level `REQUIRE_IAP_IDENTITY=true`:
a verified Bearer is required; IAP email header alone is **401**. Do **not** re-enable Cloud Run
IAP on this service. **Architecture B is the intended authorized identity:** browser JSON
sends a GIS user Bearer (`aud` = OAuth client) to admin-api as the resource server. Master yaml
was reverted in `2094211`; ARCH-B is re-shipping the bake. **Bake ≠ live traffic** until that
cutover — do not invent a traffic percent. nginx `/api` remains for Server-Sent Events and
empty-VITE local/emergency rollback — not a standing prod JSON path.

## DROP ops (Wave B)

| Surface | Endpoints (representative) |
|---------|----------------------------|
| Pipeline status / spine proxies | `GET /ops/drop/pipeline`, download/land/promote/dispatch/match/fulfill proxies |
| Cheap tickers | `GET /ops/drop/pipeline/summary`, `GET /ops/drop/console/snapshot`, `GET /ops/drop/matching-progress` |
| Hash-index refresh | `POST .../hash-index-refresh/enqueue`, `.../enqueue-all`, `.../process` |
| Matching results | list/detail (attempt history + allowlisted `audit_payload`), promote/decline (individual + bulk) |
| Assign / escalate | `POST /ops/drop/workflow/assign`, `.../escalate`, `GET .../assignments` |
| Health / fleet | `GET /ops/workers/fleet`, `GET /ops/drop/workers`, `GET /ops/health/queues`, `GET/PATCH /ops/health/retry-config`, `GET|PATCH /ops/workers/schedules`, attempt-table browser under `/ops/workers/attempt-tables*` |
| Home summary | `GET /ops/drop/stats/global` |

Header, snapshot, and matching-progress are cheap tickers: no `drop_raw_requests` spine; matching-progress is one `GROUP BY status` on `matching_attempts` only (no JOIN `requests`); sequential awaits on one asyncpg connection; `statement_timeout` 4s on those acquires. The prod hang on admin-api-prod-00078 was a DB stall (COUNT/JOIN over ~1.84M rows), not a missing route; `GET /me` stayed fast. Do not apply this budget to `GET /ops/drop/pipeline` full spine.

Browser never calls workers — admin_api aggregates `/readyz` + Postgres queue depths.

## Vertical connectors

Owner onboarding is **vertical assignment + authenticated login** — not invite links. Super_admin assigns
owners via `/ops/verticals/assignments`; owners complete setup in the `/owner/connectors` wizard
(Mode → in-wizard connect+test → cadence → confirm). Connection-credential invite mint/redeem
(`POST .../invites`) is retired (**410**). `data_user` teammate invite handlers exist
(`GET/POST /connect/{token}`) but `owner_router` is **not mounted** — do not claim teammate invites shipped.

| Surface | Endpoints (representative) |
|---------|----------------------------|
| Vertical catalog + assignments | `GET/POST/DELETE /ops/verticals`, `GET/POST/DELETE /ops/verticals/assignments`, bindings |
| Ops connections admin | `GET/POST/DELETE /ops/connections`, `POST .../test`, `POST .../wizard/reset` |
| Owner wizard | `GET/POST /owner/verticals/{id}/systems/{system}/*` (mode, credentials, upload, test, wizard complete) |
| Session | `GET /me` — `given_name`, `assigned_vertical_labels`, `needs_connector_setup`, `connector_reminders` |

Secrets write to Secret Manager only (`dpra/connections/{system}/{connection_id}`). Connection
tests return allowlisted `detail` codes — never echo credentials. All mutations require a
verified Bearer on deployed admin-api (`REQUIRE_IAP_IDENTITY`). Browser Architecture B reaches
admin-api with a GIS user Bearer. nginx `/api` remains for Server-Sent Events and
local/emergency rollback (SA Bearer + IAP headers) — not a standing prod JSON path. CLI:
`habeas-cli auth login --adc` or `auth login` (`ADMIN_API_ID_TOKEN_AUDIENCE` + `IAP_OAUTH_CLIENT_ID`).

Plan: [`docs/plans/2026-08-11-001-feat-vertical-scoped-connectors-plan.md`](../../docs/plans/2026-08-11-001-feat-vertical-scoped-connectors-plan.md).

## Per-vertical dispositions

`request_vertical_dispositions` is the source of record for the gates fulfillment reads.

| Surface | Endpoints |
|---------|-----------|
| List | `GET /requests/{request_id}/dispositions` |
| Upsert | `PUT /requests/{request_id}/dispositions/{vertical}` (`status` 3/4/5, `dwids`, `vendor_record_ids`, `early_advance`) |

Wave M live write keys are `data`, `auth0`, `communications`, and `people_hr`. Catalog systems Axios HQ (`axios_hq`), Lever, and Paylocity are treated live for write-gates (aliases → `communications` / `people_hr`) — not extra live write keys. Retracted slug `axios_headquarters` is unknown on disposition/kickoff writes. Cassandra and BizDev stay catalog-only and rejected on write. Cassandra is suppress-only — no matching, hash-refresh, or dbt. Status 3/4 require a selection (`dwids` for `data`, defaulting to the matching result; `vendor_record_ids` for Auth0 / Communications / People/HR); status 5 requires none. Matching promote upserts the `data` disposition and keeps `drop_raw_requests.response_status` in sync. Selected ids reach authorized callers only — audit records counts.

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

## Remaining verticals (Wave M)

Matching runs **after a mapped upload** (owner CSV + `column_mapping` → `gcs_uri` hash extract → `{system}_hashed_raw` → dbt mart → remaining matching enqueue). Live connection fail: **Retry connection** or **Set up manual upload**. Do not treat a successful live ping as ready-to-match.

Display **Axios HQ**. Remaining-ops aliases `axios_hq` → worker slug `axios_headquarters`. Retracted slug `axios_headquarters` is unknown on disposition/kickoff writes — not a second catalog system. Do not invent `axios_hashed_raw` (table stays `axios_headquarters_hashed_raw`).

Cassandra is **suppress-only** (Data-vertical DWID). Not on remaining-ops (404). No matching, hash-refresh, dbt, or mapping wizard. Prod worker stays stub / do-not-write until Jose.

Do **not** invent vendor APIs: Axios HQ is upload-every-batch (no HTTP); Lever S01 **no-go** (`GET /v1/users` is staff, not candidates); Paylocity S02 **no-go** (SFTP `listdir` is not a file schema). Memos: [`tmp/lever-email-extract-research.md`](../../tmp/lever-email-extract-research.md), [`tmp/paylocity-email-extract-research.md`](../../tmp/paylocity-email-extract-research.md). matching-dev stays DROP-only — remaining-vertical matching does not go through matching-dev.

| Surface | Endpoints | Role |
|---------|-----------|------|
| Hash refresh | `POST /ops/verticals/{system}/hash-refresh/enqueue`, `POST .../process` | `super_admin` |
| Matching enqueue / process | `POST /ops/verticals/{system}/matching/enqueue`, `POST .../process` | `super_admin` |
| Match candidates | `GET /requests/{request_id}/verticals/{system}/match-candidates` | `data_owner`, `admin`, `legal`, `super_admin` |
| Lab probe | `GET .../match-candidates/status` | same |

Allowlisted `{system}`: `axios_headquarters` (alias `axios_hq`), `paylocity`, `lever`, `hr_alumni`, `bizdev_contacts`. Sheets / `bizdev` stay not live for journey write-gates. Worker URLs are settings-only; do not invent `*.run.app` hosts.

## Local

```bash
uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir app/admin_api/src
```

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
