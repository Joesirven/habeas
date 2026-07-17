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

Land/promote only — no `DROP_API_KEY`. Needs `DATABASE_URL` + `DROP_PARSED_BUCKET`.

### GCS staging (ADR-32)

| Bucket | Purpose | Writers | Readers |
|--------|---------|---------|---------|
| `example-gcp-project-drop-inbound-dev` | CPPA download ZIPs | `drop-connector` | `drop-ingestor` |
| `example-gcp-project-drop-parsed-dev` | Per-list CSVs after land | `drop-ingestor` | future notice/fulfill |

Object layout:

```text
gs://…-drop-inbound-dev/inbound/{yyyy}/{mm}/{dd}/drop_download_{ts}.zip
gs://…-drop-parsed-dev/parsed/{NDZ|Email|Phone}/{yyyy}/{mm}/{dd}/{source_csv_filename}
```

Env: `DROP_INBOUND_BUCKET`, `DROP_PARSED_BUCKET` (required; no local/`file://` staging).

### Cloud Run auth (dev)

| Surface | Invoker |
|---------|---------|
| `admin-api-dev` | `allUsers` (Firebase SPA CORS; IAP later) |
| Workers (`drop-connector-dev`, `drop-ingestor-dev`, `request-dispatcher-dev`, `data-fulfillment-dispatcher-dev`, `matching-dev`) | Runtime SA of admin-api only (`95660886550-compute@developer.gserviceaccount.com`) |

Admin-api attaches a Google ID token when proxying to `*.run.app` workers (`admin_api.cloud_run_auth`). Localhost worker URLs skip auth.

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

## Manual deploy (dev)

```bash
gcloud builds submit --config=infra/cloudbuild/reaper.yaml --project=example-gcp-project .
```
