# DROP hash index — dbt project

Production BigQuery [dbt](https://docs.getdbt.com/) project for DROP v1.2.0 hash-index
refresh. Materializes serving tables `email_hash`, `phone_hash`, and `ndz_hash` in
`example-gcp-project.drop_hash_index` for DROP matching.

**GCP project:** `example-gcp-project` · **Dataset:** `drop_hash_index` · **Region:** `us-east4`

The experiment sandbox `drop_hash_experiment` (under the old `analytics/` tree in other
branches) is **not** updated by this project.

## Prerequisites

- [Google Cloud SDK](https://cloud.google.com/sdk) with Application Default Credentials
- BigQuery read on `example-gcp-project.person_db`, write on `example-gcp-project.drop_hash_index`
- Python 3.12+ and [UV](https://docs.astral.sh/uv/) (for `drop_normalize` tests)

## One-time setup

```bash
bq mk --dataset --location=us-east4 \
  --description="DROP hash index (production serving)" \
  example-gcp-project:drop_hash_index

cd transform/drop_hash
uv venv .venv
uv pip install --python .venv/bin/python dbt-bigquery
cp profiles.yml.example profiles.yml
chmod +x udf/apply_udf.sh
./udf/apply_udf.sh
```

## Build for a state (default CA)

```bash
cd transform/drop_hash
DBT_PROFILES_DIR=. dbt build --vars '{state: CA}'
```

`state` filters MDR staging (`stg_person`, `stg_phones`). Intermediate models keep
`*_std` columns plus per-field hashes; serving marts expose `(hash, dwid, state)`.

| Layer | Examples | Notes |
|-------|----------|-------|
| Staging | `stg_person`, `stg_phones` | `state = var('state')` |
| Intermediate | `int_email_hash`, `int_phone_hash`, `int_dob_hash`, `int_zip_hash`, `int_name_hash`, `int_ndz_hash` | `*_std` + hash columns |
| Serving | `email_hash`, `phone_hash`, `ndz_hash` | Built as `*_build` then swapped in |

### Phone rows

`stg_phones` emits **one row per available phone type**. When MDR has both cell and
land numbers, `phone_hash` serving gets **two rows** for that `dwid` (distinct hashes).
The experiment coalesced cell-over-land in a single row; production preserves both.

### Serving swap

Mart models write to `email_hash__build`, `phone_hash__build`, `ndz_hash__build`.
On successful `dbt build`, `perform_serving_swap()` renames build tables into the live
serving names so a failed run never replaces live tables with empty results.

Disable swap (e.g. dry run): `--vars '{perform_serving_swap: false}'`.

## Tests

CPPA golden vectors: `tests/assert_cppa_*_vector.sql` (literal inputs, no MDR PII).

```bash
cd transform/drop_hash/drop_normalize
uv run pytest tests -q
```

## Worker contract

Hash-index refresh worker (Unit 3) runs from this directory:

```bash
dbt build --vars '{state: CA}'
```

See [RUNBOOK.md](RUNBOOK.md) for operator steps.
