# BigQuery JS UDF name arm (Arm B)

Persistent UDF `example-gcp-project.drop_hash_experiment.normalize_name` — JS port of
`analytics/drop_normalize` name rules (maps from the same JSON tables).

## Apply UDF

```bash
chmod +x analytics/udf/apply_udf.sh
./analytics/udf/apply_udf.sh
```

## Vector check

```bash
bq query --use_legacy_sql=false --project_id=example-gcp-project \
  < analytics/udf/tests/test_udf_vectors.sql
```

Expect **zero rows** (all assertions pass).

## Build CA tables (dbt)

```bash
cd analytics
DBT_PROFILES_DIR=. .venv/bin/dbt run --select arm_udf_name_hash arm_udf_ndz_hash
```

Writes:

- `drop_hash_experiment.arm_udf_name_hash`
- `drop_hash_experiment.arm_udf_ndz_hash`

## Timeout → chunk recipe

If the full-CA UDF query exceeds slot time or hits a timeout:

1. Materialize in ranges of `dwid` (string or hash-mod buckets), e.g.:

```sql
CREATE OR REPLACE TABLE `example-gcp-project.drop_hash_experiment.arm_udf_name_hash_p00` AS
SELECT ... FROM stg_ca_person
WHERE MOD(ABS(FARM_FINGERPRINT(CAST(dwid AS STRING))), 10) = 0;
```

2. Repeat for `0..9`, then:

```sql
CREATE OR REPLACE TABLE `...arm_udf_name_hash` AS
SELECT * FROM `...arm_udf_name_hash_p00`
UNION ALL SELECT * FROM `...arm_udf_name_hash_p01`
-- ...
```

3. Build NDZ from the unioned name table + `int_ca_dob_hash` / `int_ca_zip_hash`.

Record bytes billed and wall time into `arm_run_metrics` (see compare RUNBOOK).

## Future triggers

Same entrypoints: re-apply UDF SQL if JS changes, then `dbt run --select tag:arm_udf`
(or Cloud Scheduler → Cloud Build that runs those commands).
