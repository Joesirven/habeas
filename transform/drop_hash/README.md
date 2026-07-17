# DROP hash index — dbt project

Production BigQuery [dbt](https://docs.getdbt.com/) project for DROP v1.2.0 hash-index
refresh. Materializes serving tables `email_hash`, `phone_hash`, and `ndz_hash` in
`example-gcp-project.drop_hash_index` for DROP matching.

**GCP project:** `example-gcp-project` · **Dataset:** `drop_hash_index` · **Region:** `us-east4`

**Production dbt home:** this directory only (`transform/drop_hash/`). The experiment
sandbox `drop_hash_experiment` (formerly under `analytics/` in pre-migration branches) is
**not** updated by this project.

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

## Build for a state

Shared marts hold all served states; each dbt run fills **one** state. Default
`state: CA` in `dbt_project.yml` is local convenience only — production passes the
attempt’s state (ops can enqueue one state or all via admin-api
`POST /ops/drop/hash-index-refresh/enqueue` / `.../enqueue-all`).

```bash
cd transform/drop_hash
DBT_PROFILES_DIR=. dbt build --vars '{state: CA}'
DBT_PROFILES_DIR=. dbt build --vars '{state: NY}'
```

`state` filters MDR staging (`stg_person`, `stg_phones`). Intermediate models keep
`*_std` columns plus per-field hashes; serving marts expose `(hash_value, dwid, state, built_at)`.

| Layer | Examples | Notes |
|-------|----------|-------|
| Staging | `stg_person`, `stg_phones` | `state = var('state')` |
| Intermediate | `int_email_hash`, `int_phone_hash`, `int_dob_hash`, `int_zip_hash`, `int_name_hash`, `int_ndz_hash` | `*_std` + hash columns |
| Serving | `email_hash`, `phone_hash`, `ndz_hash` | Built as `*_build` then swapped in |

### Serving schema

Production lookup tables in `example-gcp-project.drop_hash_index`:

| Table | Columns | Clustering |
|-------|---------|------------|
| `email_hash` | `hash_value`, `dwid`, `state`, `built_at` | `(state, hash_value)` |
| `phone_hash` | same | same |
| `ndz_hash` | same | same |

`hash_value` is Base64(SHA-256) of the DROP-standardized field (or NDZ composite).
`app/matching` lookups filter on `(hash_value, state)` with `@lookup_state` = the
requester’s normalized source state (never out-of-state DWIDs).

### Phone rows

`stg_phones` emits **one row per available phone type**. When MDR has both cell and
land numbers, `phone_hash` serving gets **two rows** for that `dwid` (distinct hashes).

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

Hash-index refresh worker runs from this directory with the attempt’s state:

```bash
dbt build --vars '{state: <STATE>}'
```

After each successful refresh, the worker enqueues rematch matching attempts for
open DROP candidates whose normalized source state equals that refreshed state.

See [RUNBOOK.md](RUNBOOK.md) for operator steps.
