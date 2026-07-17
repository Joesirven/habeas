# BigQuery JS UDF — DROP name standardization

Persistent UDF `example-gcp-project.drop_hash_index.normalize_name` — JS port of
`drop_normalize` name rules (maps from the same JSON tables).

Apply from `transform/drop_hash/udf/` (not the legacy `analytics/udf/` experiment path).

## Apply UDF

```bash
chmod +x transform/drop_hash/udf/apply_udf.sh
./transform/drop_hash/udf/apply_udf.sh
```

## Vector check

```bash
bq query --use_legacy_sql=false --project_id=example-gcp-project \
  < transform/drop_hash/udf/tests/test_udf_vectors.sql
```

Expect **zero rows** (all assertions pass).

## Build name + NDZ intermediates (dbt)

```bash
cd transform/drop_hash
DBT_PROFILES_DIR=. dbt run --select int_name_hash int_ndz_hash --vars '{state: CA}'
```

## Timeout → chunk recipe

If the full-state UDF query exceeds slot time or hits a timeout:

1. Materialize in ranges of `dwid` (string or hash-mod buckets), e.g.:

```sql
CREATE OR REPLACE TABLE `example-gcp-project.drop_hash_index.int_name_hash_p00` AS
SELECT ... FROM stg_person
WHERE MOD(ABS(FARM_FINGERPRINT(CAST(dwid AS STRING))), 10) = 0;
```

2. Repeat for `0..9`, then union into `int_name_hash`.
3. Build NDZ from the unioned name table + `int_dob_hash` / `int_zip_hash`.

## Sandbox note

The experiment dataset `drop_hash_experiment` (and its `normalize_name` UDF) remain
for the CA bake-off. Production refresh uses `drop_hash_index` only.
