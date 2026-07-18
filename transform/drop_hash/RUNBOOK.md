# RUNBOOK — DROP hash index refresh (dbt)

Operator steps for production hash-index rebuild in `example-gcp-project.drop_hash_index`.

**Canonical dbt path:** `transform/drop_hash/` only. Do not `cd analytics` for production
refresh — that tree was the pre-migration CA bake-off sandbox.

## Serving schema

| BigQuery table | Columns |
|----------------|---------|
| `example-gcp-project.drop_hash_index.email_hash` | `hash_value`, `dwid`, `state`, `built_at` |
| `example-gcp-project.drop_hash_index.phone_hash` | same |
| `example-gcp-project.drop_hash_index.ndz_hash` | same |

All three are clustered on `(state, hash_value)`. Matching lookups use `hash_value` + `state`.

## Prerequisites

- ADC / service account with BigQuery Data Editor on `drop_hash_index`, read on `person_db`
- `normalize_name` UDF deployed (see `udf/README.md`)

## 1. Normalize package tests (optional gate)

```bash
cd transform/drop_hash/drop_normalize
uv run pytest tests -q
```

## 2. Apply / refresh name UDF

```bash
./transform/drop_hash/udf/apply_udf.sh
bq query --use_legacy_sql=false < transform/drop_hash/udf/tests/test_udf_vectors.sql
```

Expect **0 rows** from the vector query.

## 3. Full dbt build + serving swap (per state)

Shared marts hold all served states; each dbt run fills **one** state:

```bash
cd transform/drop_hash
cp profiles.yml.example profiles.yml   # if needed
DBT_PROFILES_DIR=. dbt build --vars '{state: CA}'
DBT_PROFILES_DIR=. dbt build --vars '{state: TX}'
# Or enqueue the full wave via admin-api:
#   POST /ops/drop/hash-index-refresh/enqueue-all
```

Writes intermediates, builds `*_hash__build` marts, then merges that state’s rows
into `email_hash`, `phone_hash`, `ndz_hash`. Parallel per-state jobs are OK;
watch BigQuery slots/cost. Confirm served-state list with Jose (Q6) before first
prod enqueue-all wave.

**Timeout (name UDF):** chunk by `FARM_FINGERPRINT(dwid) % N` — see `udf/README.md`.

## 4. Verify serving row counts

```bash
bq query --use_legacy_sql=false '
SELECT "email_hash" AS mart, COUNT(*) AS rows FROM `example-gcp-project.drop_hash_index.email_hash`
UNION ALL SELECT "phone_hash", COUNT(*) FROM `example-gcp-project.drop_hash_index.phone_hash`
UNION ALL SELECT "ndz_hash", COUNT(*) FROM `example-gcp-project.drop_hash_index.ndz_hash`
'
```

## Experiment sandbox (non-prod)

CA bake-off artifacts may still exist in BigQuery dataset `drop_hash_experiment`
(historical code lived under `analytics/` on pre-migration branches). That dataset
and any local experiment worktrees are **not** part of this production dbt project.

## Live multi-state builds (A10)

**Allowlist:** USPS 50 states + DC (**51** codes) in
`habeas_privacy_core.geo.state.USPS_STATES_PLUS_DC` until Jose confirms a different
MDR/DROP source of truth (**Q6**).

**Enqueue-all wave (code complete — do not fire against prod without Jose):**

All enqueue/process calls go through **admin-api behind Identity-Aware Proxy**.
Do not curl workers, grant yourself worker `run.invoker`, or use `DATABASE_URL` for
mutations. Empty `POST /enqueue` does **not** default to CA — use `--state` or
`--all-states` / `enqueue-all`. See `infra/README.md` (“Calling admin-api with IAP”).

```bash
export ADMIN_API_URL=https://admin-api-dev-hsa55rg7ja-uk.a.run.app
export IAP_OAUTH_CLIENT_ID=95660886550-cpdl76minmdshvi7vcchcqivkjdna3f7.apps.googleusercontent.com
export IAP_IMPERSONATE_SERVICE_ACCOUNT=95660886550-compute@developer.gserviceaccount.com
export IAP_ID_TOKEN="$(gcloud auth print-identity-token \
  --audiences="$IAP_OAUTH_CLIENT_ID" \
  --impersonate-service-account="$IAP_IMPERSONATE_SERVICE_ACCOUNT" \
  --include-email)"
curl -sS -H "Authorization: Bearer $IAP_ID_TOKEN" "$ADMIN_API_URL/auth/me"
```

| Surface | Entry |
|---------|--------|
| Admin-api | `POST /ops/drop/hash-index-refresh/enqueue-all` (IAP bearer) → `enqueue_hash_index_refresh_all_states` |
| Web | Drop ops → Pipeline → Configurations → **Enqueue all states** (local: Vite `/api`; remote needs IAP) |
| CLI | `habeas-cli drop hash-index-refresh enqueue --all-states --execute` with `ADMIN_API_URL` + IAP SA token |
| Process | `habeas-cli drop hash-index-refresh process --execute` (admin-api proxies the worker; never call worker `/process` as a user) |
| Worker | Invoked only by admin-api runtime SA (`roles/run.invoker` on workers — never user/IAP) |

Parallel per-state `dbt build --vars '{state: …}'` into shared serving marts is
supported (staging/int/build relations are state-suffixed). Watch BigQuery
slots/cost. Prefer the queue/worker path over ad-hoc prod dbt.

**FL phone gap (2026-07-17):** After the first enqueue-all wave, `phone_hash`
had every served state except `FL` while MDR `person_db.phones` had ~20.5M FL
rows and `ndz_hash` retained FL — caused by shared unsuffixed `*_hash__build`
tables racing under parallel workers. Fixed via state-suffixed aliases; re-enqueue
FL only after the fix is deployed:

```bash
# Requires IAP SA token (see copy-paste block above) — not DATABASE_URL.
habeas-cli drop hash-index-refresh enqueue --state FL --execute
```

### Read-only BQ probe (2026-07-17, operator ADC)

Project `example-gcp-project` · account `dev-owner-1@example.com` · `bq ls` / metadata queries OK.

| Mart | Row count | Distinct `state` | Notes |
|------|-----------|------------------|--------|
| `email_hash` | 0 | 0 | Empty — CA email rebuild incomplete or never swapped |
| `phone_hash` | ~37.9M | 1 (`CA`) | Multi-state not loaded |
| `ndz_hash` | ~35.9M | 1 (`CA`) | Multi-state not loaded |

Dataset `drop_hash_index` lists serving + intermediate tables; experiment dataset
`drop_hash_experiment` still present (sandbox only).

### Blockers before first prod enqueue-all / multi-state dbt wave

1. **Prod-write gate** — no prod dbt build and no prod `enqueue-all` without Jose
   approval (see `.agent/modules/prod-write-gate.md`).
2. **Q6 / A10** — confirm 50+DC is the served-state source of truth.
3. **CA completeness** — `email_hash` is empty while phone/ndz are CA-only; fix CA
   email before scaling the wave.
4. **Worker workload identity** — Cloud Build does not yet attach a dedicated
   `hash-index-refresh` runtime SA with BigQuery `jobUser` + dataset write on
   `drop_hash_index` + MDR read (see `infra/README.md` go-live checklist). Invoker
   IAM for admin-api → worker is separate (`hash-index-refresh-dev-iam.yaml`).
5. **Ops tooling gap (local)** — `gcloud run services describe` may fail if the
   local Cloud SDK Python env lacks `grpc`; use a healthy `gcloud` / Cloud Console
   to verify the worker SA. Does not block `bq` metadata probes.

## Future triggers

| Entrypoint | Invoker |
|------------|---------|
| `dbt build --vars '{state: <STATE>}'` from `transform/drop_hash/` | Hash-index refresh worker (`app/hash_index_refresh`) — rematch-on-refresh for that state |
| `POST /ops/drop/hash-index-refresh/enqueue-all` | Admin-api full wave (A10 allowlist; confirm Q6 + Jose before prod) |
| `./udf/apply_udf.sh` | When `normalize_name.js` changes |
