# Auth0 worker

User matching and block/revoke suppression via Auth0 Management API.

Owner wizard method: Auth0 Management API. Upload is not a working path (no CSV template; API 422).

Hash in worker → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/) dbt marts. Queue: `auth0_attempts` (`step` = `matching` | `suppression`).

Cloud Run FastAPI app — health + step routes. Matching (`POST /matching/submit`) looks up the Auth0 mart; suppression still uses `adapters/stub.py`. Hash refresh runs the Auth0 **users-export job**, hashes emails in memory, writes hashed raw, then runs dbt. Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Cloud Run `auth0-dev` is not deployed.** First deploy is Jose-gated (`infra/cloudbuild/auth0-dev.yaml`, S08). There is no Scheduler job and no live `*.run.app` Auth0 worker. Hash-refresh **process** (`POST /hash-refresh/process`) and matching **submit** (`POST /matching/submit`) are **local uvicorn**. Admin-api can enqueue (and, when also local, proxy process) — see [Auth0 matching on dev](#auth0-matching-on-dev). Do not invent a Cloud Run URL. Do not claim the service is live.

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)

## Hash refresh

`POST /hash-refresh/process` claims `vertical_hash_refresh_attempts` for `system=auth0`, then:

1. Load machine-to-machine credentials from Secret Manager. Logical path `dpra/connections/auth0/{connection_id}` maps to GSM secret id `dpra-connections-auth0-{connection_id}` (slashes → hyphens). JSON keys: `domain`, `client_id`, `client_secret` — values never in git, logs, or audit payloads.
2. Run the Auth0 Management API **users-export job** (`POST /api/v2/jobs/users-exports`, poll job, download gzipped NDJSON). Required scope `read:users`. Hash emails in memory (DROP v1.2.0 / CPPA). Skip users without a hashable email. This is a full export — not `GET /api/v2/users` paging. Optional `AUTH0_USERS_MAX_PAGES` is a test-only yield cap that **aborts** with `export_incomplete` (not page/per_page).
3. Write `example-gcp-project.external_hash_index.auth0_hashed_raw` with hashed columns only: `email_hash`, `vendor_record_id`, `system`, `extracted_at`. Empty incoming rows must not wipe a prior good index — empty `WRITE_TRUNCATE` is being removed in the hashed-raw writer (do not treat `rows_written=0` as a successful replace).
4. Run `dbt build --select stg_auth0_hashed mart_auth0_email_hash` from [`transform/external_hash`](../../transform/external_hash/) (physical alias `auth0_email_hash__build`).

dbt never sees plaintext email. Do not log emails, `client_secret`, download URLs, or raw Management API payloads.

Super_admin enqueue is admin-api `POST /ops/verticals/auth0/hash-refresh/enqueue` (see [Auth0 matching on dev](#auth0-matching-on-dev)). There is **no** Habeas CLI wrapper — `habeas-cli drop hash-index-refresh` is the DROP hash index, a different queue. Core helper below is a fallback when admin-api is not running. Hash refresh is **not** auto-scheduled.

**Cadence is UNSET and out of scope.** Do not persist `refresh_policy`, stamp `last_successful_refresh_at`, or block matching on refresh age.

One `AUTH0_CONNECTION_ID` per local run (UUID of `integration_connections.id`). No production dataset create or prod dbt without Jose.

### `AUTH0_CONNECTION_ID` lookup

The Connections UI (`/ops/connections`) does **not** show the UUID (`id` is a React key only). There is **no** `habeas-cli connections` command.

Verified paths (copy `id` where `system` is `auth0`):

1. Admin-api `GET /ops/connections` (super_admin) returns `connections[].id`. No system query param — filter the JSON. No CLI wrapper for this route; do not invent one.
2. Habeas SELECT-only wrapper — table `integration_connections`, column `id`:

```bash
uv run --package habeas-cli habeas-cli db query \
  "SELECT id, system, display_name, status FROM integration_connections WHERE system = 'auth0'"
```

GSM secret for that row must already exist from connections onboarding (`dpra-connections-auth0-{id}`).

### Environment

| Variable | Role |
|----------|------|
| `AUTH0_CONNECTION_ID` | UUID from lookup above; logical path `dpra/connections/auth0/{id}` → GSM id `dpra-connections-auth0-{id}` |
| `GCP_PROJECT` | GCP project for Secret Manager + BigQuery (typically `example-gcp-project`) |
| `EXTERNAL_HASH_DBT_DIR` | Path to [`transform/external_hash`](../../transform/external_hash/); worker dbt defaults `DBT_PROFILES_DIR` here |
| `DBT_PROFILES_DIR` | Directory that contains `profiles.yml` (defaults to `EXTERNAL_HASH_DBT_DIR` if unset) |
| `BQ_DATASET` | Optional override; default `external_hash_index` |
| `DATABASE_URL` | Postgres for the claim/run queue. Required for process (503 without it). Never commit. |
| `SKIP_EXTERNAL_HASH_DBT` | `true` for extract-only (skip worker dbt). Default false. |
| `AUTH0_USERS_MAX_PAGES` | Optional test-only yield cap. Aborts the export as incomplete — not page/per_page. Omit for a full export. |
| `SECRET_READER` | Tests only (`memory`). Local extract uses GSM + ADC (`GCP_PROJECT` set). |

### Local extract + dbt

`auth0-dev` Cloud Run is **not deployed** (Jose + `infra/cloudbuild/auth0-dev.yaml`, S08). Use local uvicorn. Needs ADC, live `DATABASE_URL`, GSM accessor on `dpra-connections-auth0-{connection_id}`, and a dataset that already exists. Local extract is GSM + ADC — `SECRET_READER=memory` is not an operator path.

Numbered blockers **before** enqueue / uvicorn / curl:

1. **`AUTH0_CONNECTION_ID`** — lookup above.
2. **Dataset + hashed-raw table (Jose-gated).** Do not create the production dataset or table without Jose. Commented `bq mk` and `CREATE TABLE` live in [`transform/external_hash/README.md`](../../transform/external_hash/README.md) (Auth0 hashed-raw contract). Sequence them **before** extract (`load_table_from_json` can create the table only if the **dataset** already exists):

```bash
# Jose / OQ1 only — do not run in prod without approval:
# bq mk --dataset --location=us-east4 \
#   --description="External vertical hash index (hashed raw + serving marts)" \
#   example-gcp-project:external_hash_index
#
# Then apply the hashed-raw DDL from transform/external_hash/README.md
# (`CREATE TABLE … auth0_hashed_raw` — hash columns only, no plaintext email).
```

3. **`profiles.yml` before the worker.** `POST /hash-refresh/process` runs dbt unless `SKIP_EXTERNAL_HASH_DBT=true`. Worker `dbt_runner` sets `DBT_PROFILES_DIR` to `EXTERNAL_HASH_DBT_DIR` when unset. There is no `transform/external_hash/profiles.yml.example`. Copy the existing DROP example and edit two names (gitignored; warehouse auth is ADC `method: oauth` — do not invent credentials):

```bash
cd transform/external_hash
cp ../drop_hash/profiles.yml.example profiles.yml
# Required edits vs drop_hash/profiles.yml.example:
#   profile key `drop_hash` → `external_hash`  (matches dbt_project.yml)
#   dataset `drop_hash_index` → `external_hash_index`
```

```bash
uv sync --all-packages
gcloud auth application-default login   # once per machine

export GCP_PROJECT=example-gcp-project
export AUTH0_CONNECTION_ID='<id from lookup>'
export DATABASE_URL='postgres://…'   # live URL; never commit
export EXTERNAL_HASH_DBT_DIR="$(pwd)/transform/external_hash"
export DBT_PROFILES_DIR="$EXTERNAL_HASH_DBT_DIR"

# Preferred: admin-api enqueue (super_admin). Local admin-api default port 8000.
# curl -sS -X POST http://127.0.0.1:8000/ops/verticals/auth0/hash-refresh/enqueue
#
# Fallback — core helper against DATABASE_URL (no CLI wrapper):
uv run --package auth0-worker python -c "
import asyncio, os, asyncpg
from habeas_privacy_core.db.vertical_hash_refresh import enqueue_vertical_hash_refresh

async def main():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    try:
        print(await enqueue_vertical_hash_refresh(conn, system='auth0'))
    finally:
        await conn.close()

asyncio.run(main())
"

# Local only — Cloud Run auth0-dev is not deployed
uv run --package auth0-worker uvicorn auth0.main:app \
  --reload --app-dir app/auth0/src --port 8080

curl -sS -X POST http://127.0.0.1:8080/hash-refresh/process
```

Extract-only (skip worker dbt): `export SKIP_EXTERNAL_HASH_DBT=true` before uvicorn.

Manual dbt after hashed raw is present — use the worker package (has `dbt-bigquery`) or the [external_hash one-time setup](../../transform/external_hash/README.md). Do **not** commit `profiles.yml`.

```bash
export DBT_PROFILES_DIR="$(pwd)/transform/external_hash"
uv run --package auth0-worker dbt parse --project-dir transform/external_hash
uv run --package auth0-worker dbt build --project-dir transform/external_hash \
  --select stg_auth0_hashed mart_auth0_email_hash
```

```bash
uv run --package auth0-worker pytest app/auth0/tests -q
```

### Stuck single-flight

`enqueue_vertical_hash_refresh` is single-flight: a non-terminal row (`pending` / `claimed` / `in_flight`) is returned again — no second insert. Claim takes `pending` only. Process marks `in_flight` immediately. Crash after that → `POST /hash-refresh/process` returns idle; enqueue reprints the stuck id.

There is **no** admin-api abandon/retry route for this table. Do **not** DELETE rows (`db/AGENTS.md`).

Verified recovery (reaper, `supports_attempt_retry=False` — lease / stuck-in-flight only; operator re-enqueue after terminal):

| State | Cleared when | Then |
|-------|----------------|------|
| `claimed` and `claim_expires_at` elapsed | Reaper `release_dead_claims` → `timeout` (worker lease `hash_refresh_lease_minutes`, default 60) | Re-enqueue |
| `in_flight` and `submitted_at` older than 4 hours | Reaper `release_stuck_in_flight` (`in_flight_max_wait_hours=4`) → `timeout` | Re-enqueue |

Local extract usually has no reaper. Inspect (SELECT-only):

```bash
uv run --package habeas-cli habeas-cli db query \
  "SELECT id, status, system, submitted_at, claim_expires_at FROM vertical_hash_refresh_attempts WHERE system = 'auth0'"
```

To mark timeout locally, run the existing reaper (`POST /reap` — see [`app/reaper/README.md`](../reaper/README.md)), then enqueue again. Tests abandon non-terminal rows; operators have no SELECT-only way to UPDATE.

### IAM (not automated)

Cloud Build YAML for `auth0-dev` is S08; the service is **not deployed** until Jose approves the first submit. Do not treat the YAML as a live URL. When a runtime identity exists, grants are an ops follow-up — see [`infra/README.md`](../../infra/README.md).

Do **not** treat dataset-wide `dataEditor` on `external_hash_index` as acceptable: that dataset also holds other vertical hashed raw / marts. Bind table-level editor on `auth0_hashed_raw` and `auth0_email_hash__build` only, plus project `jobUser` and GSM `secretAccessor` on `dpra-connections-auth0-{connection_id}`.

## Auth0 matching on dev

Email-hash matching on **dev** runs in **this worker** (`POST /matching/submit`), not `matching-dev`. **matching-dev is DROP-only** — it does not look up the Auth0 mart, does not write `request_vertical_matching`, and must **not** be granted `auth0_hashed_raw` (or dataset-wide `external_hash_index`).

Admin-api is the control plane: super_admin enqueue/process matching (S05). Users never invoke workers. The serving mart `example-gcp-project.external_hash_index.auth0_email_hash__build` must exist before this worker looks it up.

**Cadence is UNSET and out of scope.** Matching does **not** read owner freshness, `evaluate_connection_gate`, or a 12h Sheets-style gate. An UNSET cadence does **not** block the wave. Hash refresh stays **manual**.

**`auth0-dev` Cloud Run is not deployed.** First deploy is Jose-gated and needs `infra/cloudbuild/auth0-dev.yaml` (S08). Do not curl a fabricated `*.run.app` Auth0 worker. Hash-refresh **process** and matching **submit** are **local uvicorn** (port **8080**) until that deploy exists. Do not claim the service is live.

Numbered path:

1. Hash refresh enqueue / process (mart prerequisite)
2. Admin-api Auth0 matching enqueue / process (this worker `/matching/submit`)
3. Verify `request_vertical_matching`
4. Owner GET candidates + PUT disposition

### 1. Hash refresh enqueue / process

Prerequisites: `AUTH0_CONNECTION_ID`, Jose-gated dataset / hashed-raw, `profiles.yml` — [Local extract + dbt](#local-extract--dbt). Start local uvicorn first.

```bash
# Local admin-api (default role super_admin when REQUIRE_IAP_IDENTITY=false)
# AUTH0_WORKER_URL defaults to http://127.0.0.1:8080 — only reachable if admin-api is also local.
curl -sS -X POST http://127.0.0.1:8000/ops/verticals/auth0/hash-refresh/enqueue
curl -sS -X POST http://127.0.0.1:8000/ops/verticals/auth0/hash-refresh/process
```

Against **admin-api-dev**, enqueue still writes `vertical_hash_refresh_attempts`. Process **cannot** reach this laptop and there is no live Cloud Run Auth0 service — after enqueue, process locally:

```bash
curl -sS -X POST http://127.0.0.1:8080/hash-refresh/process
```

Empty mart → matching records `match_count=0`. Confirm dbt built `auth0_email_hash__build` (Jose-gated BQ row count) before blaming matching.

Env for this worker: [Environment](#environment). Admin-api process proxy: `AUTH0_WORKER_URL` (default `http://127.0.0.1:8080`) — [`app/admin_api/README.md`](../admin_api/README.md) § Auth0 vertical.

### 2. Admin-api Auth0 matching enqueue / process

Enqueue writes `auth0_attempts` (`step=matching`) for the request. Process proxies to `AUTH0_WORKER_URL` `/matching/submit` (default `http://127.0.0.1:8080`). Super_admin only. matching-dev `/ensure-drain` is the DROP wave — do not use it for Auth0 matching.

```bash
# Local admin-api. Enqueue is per request (auth0_attempts unique on request_id + step).
curl -sS -X POST "http://127.0.0.1:8000/ops/verticals/auth0/matching/enqueue" \
  -H 'Content-Type: application/json' \
  -d "{\"request_id\":\"${REQUEST_ID}\"}"
curl -sS -X POST http://127.0.0.1:8000/ops/verticals/auth0/matching/process
```

Against **admin-api-dev**, enqueue still writes `auth0_attempts`. Process **cannot** reach this laptop and `auth0-dev` is not deployed — after enqueue, process locally:

```bash
curl -sS -X POST http://127.0.0.1:8080/matching/submit
```

This worker claims the pending `auth0_attempts` row, looks up `auth0_email_hash__build` by the request’s DROP **email** hash, and upserts `request_vertical_matching`. No email hash → zero-hit snapshot (not an error). Empty mart → `match_count=0`.

Do **not** grant `auth0_hashed_raw` (or dataset-wide `external_hash_index`) to matching-dev. Mart read for this path is this worker (local ADC until Jose deploys `auth0-dev`). Table-level IAM for a future Cloud Run identity is S08 / [`infra/README.md`](../../infra/README.md) — do not treat that as live.

### 3. Verify `request_vertical_matching`

SELECT-only (counts / ids of the request — no hashes or emails):

```bash
uv run --package habeas-cli habeas-cli db query \
  "SELECT request_id, vertical, match_count, recorded_at FROM request_vertical_matching WHERE vertical = 'auth0'"
```

### 4. Owner GET candidates + PUT disposition

Roles and bodies: [`app/admin_api/README.md`](../admin_api/README.md) § Auth0 vertical.

```bash
# Local admin-api
curl -sS "http://127.0.0.1:8000/requests/${REQUEST_ID}/verticals/auth0/match-candidates"
curl -sS -X PUT "http://127.0.0.1:8000/requests/${REQUEST_ID}/dispositions/auth0" \
  -H 'Content-Type: application/json' \
  -d '{"status":4,"vendor_record_ids":["auth0|opaque-id"]}'
```

`matching.review` still opens from the DROP result.
