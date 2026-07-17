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

## Future triggers

| Entrypoint | Invoker |
|------------|---------|
| `dbt build --vars '{state: CA}'` from `transform/drop_hash/` | Hash-index refresh worker (Unit 3) |
| `./udf/apply_udf.sh` | When `normalize_name.js` changes |
