# RUNBOOK — DROP hash index refresh (dbt)

Operator steps for production hash-index rebuild in `example-gcp-project.drop_hash_index`.

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

## 3. Full dbt build + serving swap

```bash
cd transform/drop_hash
cp profiles.yml.example profiles.yml   # if needed
DBT_PROFILES_DIR=. dbt build --vars '{state: CA}'
```

Writes intermediates, builds `*_hash__build` marts, then swaps to `email_hash`,
`phone_hash`, `ndz_hash`.

**Timeout (name UDF):** chunk by `FARM_FINGERPRINT(dwid) % N` — see `udf/README.md`.

## 4. Verify serving row counts

```bash
bq query --use_legacy_sql=false '
SELECT "email_hash" AS mart, COUNT(*) AS rows FROM `example-gcp-project.drop_hash_index.email_hash`
UNION ALL SELECT "phone_hash", COUNT(*) FROM `example-gcp-project.drop_hash_index.phone_hash`
UNION ALL SELECT "ndz_hash", COUNT(*) FROM `example-gcp-project.drop_hash_index.ndz_hash`
'
```

## Experiment sandbox (leftover)

CA bake-off artifacts remain in `drop_hash_experiment`. Compare tooling under
`compare/` still targets that dataset for arm metrics — not used in production refresh.

## Future triggers

| Entrypoint | Invoker |
|------------|---------|
| `dbt build --vars '{state: CA}'` from `transform/drop_hash/` | Hash-index refresh worker (Unit 3) |
| `./udf/apply_udf.sh` | When `normalize_name.js` changes |
