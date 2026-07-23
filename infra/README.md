# Cloud Build + Artifact Registry

| File | Purpose |
|------|---------|
| [`cloudbuild/reaper.yaml`](cloudbuild/reaper.yaml) | Test, build, migrate, deploy `reaper` |
| [`cloudbuild/trigger-reaper.yaml`](cloudbuild/trigger-reaper.yaml) | Trigger definition (path-filtered) |

**Project:** `example-gcp-project` · **Region:** `us-east4` · **Artifact Registry repo:** `data-privacy`

## Provisioned (2026-07-13)

| Resource | ID |
|----------|----|
| Artifact Registry (Docker) | `us-east4-docker.pkg.dev/example-gcp-project/data-privacy` |
| Cloud SQL | `example-gcp-project:us-east4:dev-dpra` (Postgres 18) |
| Secret Manager | `database-url` (version 1 — Cloud SQL `postgres` user URL, `sslmode=require`) |
| Runtime SA | `reaper@example-gcp-project.iam.gserviceaccount.com` |
| Cloud SQL IAM DB user | `reaper@example-gcp-project.iam` |
| `roles/iam.serviceAccountUser` on reaper SA | Cloud Build SA + default compute SA (can `actAs` on deploy) |

## Temp dev database (`dpra-dev-temp`)

Use while Secret Manager / `database-url` is blocked. Do not use for production cutover until INF lands.

| Resource | Value |
|----------|-------|
| Instance | `example-gcp-project:us-east4:dpra-dev-temp` |
| Migrations | `dbmate -d db/migrations up` (local, with `.env` `DATABASE_URL`) |
| Cloud Run | `--add-cloudsql-instances=example-gcp-project:us-east4:dpra-dev-temp` + `DATABASE_URL` env var (not `--set-secrets`) |

Manual dev deploy (pass your URL; use Cloud SQL socket form for Cloud Run):

```bash
# Socket form for Cloud Run:
# postgres://postgres:PASSWORD@/postgres?host=/cloudsql/example-gcp-project:us-east4:dpra-dev-temp

gcloud builds submit --config=infra/cloudbuild/reaper-dev.yaml \
  --project=example-gcp-project \
  --substitutions=_DATABASE_URL='postgres://postgres:PASSWORD@/postgres?host=/cloudsql/example-gcp-project:us-east4:dpra-dev-temp'

gcloud builds submit --config=infra/cloudbuild/matching-dev.yaml \
  --project=example-gcp-project \
  --substitutions=_DATABASE_URL='postgres://postgres:PASSWORD@/postgres?host=/cloudsql/example-gcp-project:us-east4:dpra-dev-temp'

gcloud builds submit --config=infra/cloudbuild/drop-connector-dev.yaml \
  --project=example-gcp-project \
  --substitutions=_DATABASE_URL='postgres://postgres:PASSWORD@/postgres?host=/cloudsql/example-gcp-project:us-east4:dpra-dev-temp',_DROP_API_KEY='YOUR_SANDBOX_KEY'

gcloud builds submit --config=infra/cloudbuild/drop-ingestor-dev.yaml \
  --project=example-gcp-project \
  --substitutions=_DATABASE_URL='postgres://postgres:PASSWORD@/postgres?host=/cloudsql/example-gcp-project:us-east4:dpra-dev-temp'
```

### drop-connector (U6)

| File | Purpose |
|------|---------|
| [`cloudbuild/drop-connector-dev.yaml`](cloudbuild/drop-connector-dev.yaml) | Build/push/deploy `drop-connector-dev` |

Env on Cloud Run: `DROP_ENV=sandbox`, `DROP_API_BASE_URL=https://api.drop.privacy.ca.gov/sandbox`, `DROP_API_KEY` via `_DROP_API_KEY` substitution (prefer Secret Manager `drop-sandbox-api-key` when IAM allows). Never point sandbox deploy at production host.

### drop-ingestor (U7)

| File | Purpose |
|------|---------|
| [`cloudbuild/drop-ingestor-dev.yaml`](cloudbuild/drop-ingestor-dev.yaml) | Build/push/deploy `drop-ingestor-dev` |

Land/promote only — no `DROP_API_KEY`. Needs `DATABASE_URL`.

### admin-web-dev (static admin SPA)

| File | Purpose |
|------|---------|
| [`cloudbuild/admin-web-dev.yaml`](cloudbuild/admin-web-dev.yaml) | Build/push/deploy `admin-web-dev` |

Bun/Vite multi-stage build → nginx on port 8080. `VITE_ADMIN_API_URL` is a **build arg** (default: dev admin-api Cloud Run URL). No runtime secrets.

```bash
gcloud builds submit --config=infra/cloudbuild/admin-web-dev.yaml --project=example-gcp-project .
```

After first deploy, append the `admin-web-dev` `*.run.app` origin to `admin-api-dev` `_CORS_ORIGINS` and redeploy admin-api so the browser can call the API cross-origin.

**Requester state on promote:** `requestor_state` comes from `raw_payload.state` /
`raw_payload.requestor_state`, else a USPS token in the CSV filename
(e.g. `broker_TX_EMAIL.csv`). If both omit state, promote **fails closed** — it
does **not** invent `CA`. For local CA DROP sandbox filenames that omit state
(e.g. `20260716_1_NDZ.csv`), set opt-in env on the worker only:

```bash
DROP_ALLOW_DEFAULT_REQUESTOR_STATE=CA
```

Never enable that override in deployed/IAP environments. When it is set, promote
logs `drop_promote_requestor_state_default` (no PII) with `sandbox_override=true`.

### hash-index-refresh (DROP hash productionize)

| File | Purpose |
|------|---------|
| [`cloudbuild/hash-index-refresh-dev.yaml`](cloudbuild/hash-index-refresh-dev.yaml) | Build/push/deploy `hash-index-refresh-dev` |

Runs dbt under `transform/drop_hash/` against BigQuery `drop_hash_index`. Needs `DATABASE_URL` + workload identity with BigQuery **jobUser** and dataset write on `example-gcp-project.drop_hash_index` (read on MDR source datasets). Matching SA remains **select-only** on the three serving marts (`email_hash`, `phone_hash`, `ndz_hash`).

```bash
gcloud builds submit --config=infra/cloudbuild/hash-index-refresh-dev.yaml \
  --project=example-gcp-project \
  --substitutions=_DATABASE_URL='postgres://postgres:PASSWORD@/postgres?host=/cloudsql/example-gcp-project:us-east4:dpra-dev-temp'
```

### Cloud Run auth (dev)

| Surface | Invoker |
|---------|---------|
| `admin-api-dev` | Compute SA + allowlisted user invokers; Cloud Run **IAP off** (`--no-iap`); app-level `REQUIRE_IAP_IDENTITY` accepts IAP email header **or** verified Bearer Google ID token (ADC) |
| `admin-web-dev` / `ops-ia-web-dev` | Public Cloud Run + browser IAP front door (see `admin-web-dev.yaml` / ops-ia deploy) |
| Workers (`drop-connector-dev`, `drop-ingestor-dev`, `request-dispatcher-dev`, `data-fulfillment-dispatcher-dev`, `matching-dev`, `hash-index-refresh-dev`) | Runtime SA of admin-api only (`95660886550-compute@developer.gserviceaccount.com`) — never user/IAP direct |

Admin-api attaches a Google ID token when proxying to `*.run.app` workers (`admin_api.cloud_run_auth`). Operators never call workers directly — process/enqueue goes through admin-api. Localhost worker URLs skip auth.

**Local tooling → admin-api-dev:**

| Caller | Auth |
|--------|------|
| super_admin (CLI / local Vite) | ADC Cloud Run ID token (`habeas-cli auth login --adc` or Vite ADC proxy); email must be on `ADMIN_API_SUPER_ADMINS` |
| admin / data_owner (CLI) | `habeas-cli auth login` (Cloud Run audience token via ADC + email header bound to gcloud account) |
| Browser SSO | ops-ia / admin-web IAP front door (unchanged) |

Do **not** re-run [`admin-api-dev-iam.yaml`](cloudbuild/admin-api-dev-iam.yaml) for the ADC workflow — it re-enables Cloud Run IAP and strips user invoker.

#### DROP mutation identity (app layer)

Mutating `/ops/drop/*` routes and the power console require a DROP ops role. Deployed admin-api sets `REQUIRE_IAP_IDENTITY=true` (`_REQUIRE_IAP_IDENTITY` in `admin-api-dev.yaml`) so headerless callers get **401**; authenticated emails not on an allowlist get **403**. Local default is `false` so Vite/CLI against localhost keep working (role from `DROP_OPS_LOCAL_ROLE`, default `super_admin`).

`decided_by` on bulk-approve prefers `X-Goog-Authenticated-User-Email` when present (ignores client spoof).

#### DROP ops role allowlists

Map IAP email → role (pipe- or comma-separated). Highest privilege wins if an email is on multiple lists.

| Env | Role | Typical access |
|-----|------|----------------|
| `DROP_OPS_SUPER_ADMIN_EMAILS` | `super_admin` | Spine proxies, `GET /ops/drop/pipeline`, workers/queues, hash-index enqueue/process |
| `DROP_OPS_ADMIN_EMAILS` | `admin` | Matching-results GET/bulk-approve, assign/escalate, matching.review decide |
| `DROP_OPS_DATA_OWNER_EMAILS` | `data_owner` | Same review paths as `admin` |
| `DROP_OPS_LOCAL_ROLE` | any of the three | Local-only default when `REQUIRE_IAP_IDENTITY` is false (default `super_admin`) |

**Web session contract:** `GET /me` → `{ "email", "role", "real_role" }` (`role` is effective after optional `X-Dev-Simulate-Role`; `real_role` is the allowlist role). `GET /auth/me` is the same probe.

#### Calling admin-api (CLI) — preferred paths

```bash
export ADMIN_API_URL=https://admin-api-dev-hsa55rg7ja-uk.a.run.app

# Super_admin — ADC (Cloud Run ID token; no IAP email header)
gcloud auth application-default login
uv run --package habeas-cli habeas-cli auth login --adc
uv run --package habeas-cli habeas-cli auth status

# Admin / data_owner — IAP login (email bound to gcloud account)
export IAP_OAUTH_CLIENT_ID=95660886550-cpdl76minmdshvi7vcchcqivkjdna3f7.apps.googleusercontent.com
export IAP_IMPERSONATE_SERVICE_ACCOUNT=95660886550-compute@developer.gserviceaccount.com
uv run --package habeas-cli habeas-cli auth login

uv run --package habeas-cli habeas-cli drop pipeline
uv run --package habeas-cli habeas-cli drop hash-index-refresh process --execute
```

#### Legacy IAP mint (curl / env) — machine path

User ADC **cannot** mint IAP `--audiences` ID tokens. Mint via the ops/runtime
service account (impersonation). Audience = IAP OAuth client ID (not the Cloud Run URL).

Dev client ID:

`95660886550-cpdl76minmdshvi7vcchcqivkjdna3f7.apps.googleusercontent.com`

```bash
export IAP_ID_TOKEN="$(gcloud auth print-identity-token \
  --audiences="$IAP_OAUTH_CLIENT_ID" \
  --impersonate-service-account="$IAP_IMPERSONATE_SERVICE_ACCOUNT" \
  --include-email)"

curl -sS -H "Authorization: Bearer $IAP_ID_TOKEN" \
  -H "X-Goog-Authenticated-User-Email: accounts.google.com:you@example.com" \
  "$ADMIN_API_URL/me"
```

Prerequisites Jose must keep granted:

| Grant | Principal | Resource |
|-------|-----------|----------|
| `roles/iam.serviceAccountTokenCreator` | `user:jsirven@…` (agents) | ops SA (`95660886550-compute@…`) |
| `roles/run.invoker` | compute SA + allowlisted users (e.g. `user:jsirven@…`) | `admin-api-dev` (Cloud Run IAP **off**) |
| `ADMIN_API_SUPER_ADMINS` / admins / data_owners env | operator emails | Cloud Run env on admin-api (Bearer ADC → super_admins only) |
| Worker `roles/run.invoker` | **only** admin-api runtime SA | `hash-index-refresh-dev`, `matching-dev`, … |
| `roles/cloudscheduler.admin` | admin-api runtime SA (`95660886550-compute@…`) | project (live schedule GET/PATCH) |

Do **not** use `DATABASE_URL` for ops mutations — SELECT-only analysis only.
Do **not** curl workers or grant yourself worker `run.invoker`.

Local web against remote admin-api (super_admin ADC — Vite mints/caches ID token):

```bash
cd clients/web
# gcloud auth application-default login  # once
export VITE_PROXY_TARGET="$ADMIN_API_URL"   # admin-api-dev *.run.app
bun run dev   # leave VITE_ADMIN_API_URL unset so the app uses /api
# Banner "View as" sends X-Dev-Simulate-Role when real_role is super_admin
```

Non–super_admin browsers: use the ops-ia IAP front door, not the ADC Vite proxy.

**Residual:**

1. IAP email header path still trusts the header when present (Bearer path verifies Google ID tokens — see `habeas_privacy_core.auth` README).
2. Deployed SPA→admin-api is cross-origin; cookie IAP is best-effort (`credentials: 'include'`). Prefer CLI auth login for mutations until a same-origin `/api` BFF exists.
3. Do **not** re-run `admin-api-dev-iam.yaml` for the ADC workflow (re-enables Cloud Run IAP). Worker invoker lock:

```bash
gcloud builds submit --config=infra/cloudbuild/hash-index-refresh-dev-iam.yaml \
  --project=example-gcp-project
```

#### Workload identity least privilege (hash-index vs matching) — go-live

Cloud Build does **not** yet attach dedicated runtime service accounts (same gap as other workers besides `reaper`). Before production:

| Workload | Runtime SA (create if missing) | BigQuery |
|----------|--------------------------------|----------|
| `hash-index-refresh` | dedicated SA | `roles/bigquery.jobUser` + dataset write on `drop_hash_index` + read on MDR sources |
| `matching` | distinct SA | **select-only** on `email_hash` / `phone_hash` / `ndz_hash` (e.g. `roles/bigquery.dataViewer` at dataset or table) |

Verify after bind:

```bash
gcloud run services describe hash-index-refresh-dev --region=us-east4 --project=example-gcp-project \
  --format='value(spec.template.spec.serviceAccountName)'
gcloud run services describe matching-dev --region=us-east4 --project=example-gcp-project \
  --format='value(spec.template.spec.serviceAccountName)'
# Confirm invoker is admin-api SA only (no allUsers):
gcloud run services get-iam-policy hash-index-refresh-dev --region=us-east4 --project=example-gcp-project
```

After INF grants `secretmanager.admin`, cut over to `dev-dpra` + `database-url` and delete `dpra-dev-temp`.

## Blocked on infra IAM (historical — largely unblocked)

`dev-owner-1@example.com` now has `roles/resourcemanager.projectIamAdmin`, `roles/run.admin`, and `roles/secretmanager.admin` (plus editor / serviceAccountAdmin). Earlier note:

`dev-owner-1@example.com` previously lacked project/secret `setIamPolicy`. Ask Henry/Chris for:

1. **Secret accessors** on `database-url`:
   - `user:dev-owner-1@example.com`
   - `serviceAccount:reaper@example-gcp-project.iam.gserviceaccount.com`
   - `serviceAccount:95660886550@cloudbuild.gserviceaccount.com`
   - `serviceAccount:95660886550-compute@developer.gserviceaccount.com`
2. **Project roles on** `reaper@example-gcp-project.iam.gserviceaccount.com`:
   - `roles/cloudsql.client`
   - `roles/cloudsql.instanceUser`
   - `roles/logging.logWriter`
   - `roles/cloudtrace.agent`

Until (1) lands, Cloud Build cannot read `DATABASE_URL` and Jose cannot verify/rotate the secret.

## One-time setup (reference)

```bash
gcloud artifacts repositories create data-privacy \
  --repository-format=docker \
  --location=us-east4 \
  --project=example-gcp-project

gcloud iam service-accounts create reaper \
  --display-name='reaper Cloud Run service' \
  --project=example-gcp-project

# Secret for Cloud Build migrations + Cloud Run runtime (value never in git)
# postgres://postgres:<url-encoded-password>@<sql-public-ip>:5432/postgres?sslmode=require
echo -n 'postgres://…' | gcloud secrets create database-url \
  --data-file=- \
  --project=example-gcp-project
```

Wire the Cloud Build trigger using `cloudbuild/trigger-reaper.yaml` after connecting the Bitbucket repo.

Before first deploy, point Cloud Run at the reaper SA and Cloud SQL instance (edit `cloudbuild/reaper.yaml` deploy step):

```text
--service-account=reaper@example-gcp-project.iam.gserviceaccount.com
--add-cloudsql-instances=example-gcp-project:us-east4:dev-dpra
```

## Cloud Scheduler (worker ticks)

Workers are HTTP + queue-claim. Cloud Scheduler OIDC-invokes worker endpoints on a cadence. Schedules are **live in GCP** (no Postgres mirror). Super_admins edit them via admin-api `GET|PATCH /ops/workers/schedules` (Workers Settings / Ops Configuration UI).

| Job id pattern | Target | Default |
|----------------|--------|---------|
| `dpra-{env}-drop-connector-download` | `POST /download` | Daily `0 14 * * *` UTC + body `interval_days=15` (eligibility gate) |
| `dpra-{env}-reaper` | `POST /reap` | every 1 min |
| `dpra-{env}-drop-ingestor-land` | `POST /ingest/land` | every 5 min |
| `dpra-{env}-drop-ingestor-promote` | `POST /ingest/promote` | every 5 min |
| `dpra-{env}-request-dispatcher` | `POST /dispatch` | every 5 min |
| `dpra-{env}-matching` | `POST /process` | every 5 min |
| `dpra-{env}-data-fulfillment` | `POST /fulfill` | every 5 min |

**Scheduler SA:** `dpra-scheduler@example-gcp-project.iam.gserviceaccount.com` — grant `roles/run.invoker` on workers (infra exception; still never grant users worker invoker). OIDC audience must be the Cloud Run **service root** URL (no path). Grant Cloud Scheduler’s agent `roles/iam.serviceAccountUser` on the scheduler SA so it can mint tokens.

**Admin-api (dev):** `admin-api-dev.yaml` sets `CLOUD_SCHEDULER_ENABLED=true`, `CLOUD_SCHEDULER_LOCATION=us-east4`, `CLOUD_SCHEDULER_JOB_PREFIX=dpra-dev` (plus existing `GCP_PROJECT`). Runtime SA (`95660886550-compute@…`) needs `roles/cloudscheduler.admin` on the project (or a custom role that can get/patch/pause/resume jobs) so Workers Settings can edit live schedules.

### Upsert script (dry-run by default)

```bash
# Prints gcloud commands only
ENV=dev ./infra/scripts/upsert_worker_scheduler_jobs.sh

# Apply (dev). Prod requires Jose approval (prod-write-gate).
CONFIRM=yes ENV=dev ./infra/scripts/upsert_worker_scheduler_jobs.sh
# CONFIRM=yes ENV=prod ./infra/scripts/upsert_worker_scheduler_jobs.sh  # Jose only
```

Hash-index refresh is **not** auto-scheduled (manual/ops enqueue).

## Manual deploy (dev)

```bash
gcloud builds submit --config=infra/cloudbuild/reaper.yaml --project=example-gcp-project .
```
