# Analytics — DROP hash CA experiment (dbt)

BigQuery [dbt](https://docs.getdbt.com/) project for versioned DROP v1.2.0 cleaning SQL used in the CA MDR bake-off. Non-name fields (email, phone, ZIP, date of birth) are materialized here; name arms (Spark, JS UDF, Cloud Run) join these tables in later units.

**GCP project:** `example-gcp-project` · **Dataset:** `drop_hash_experiment` · **Region:** `us-east4`

## Prerequisites

- [Google Cloud SDK](https://cloud.google.com/sdk) with Application Default Credentials: `gcloud auth application-default login`
- BigQuery access to `example-gcp-project.person_db` (read) and `example-gcp-project.drop_hash_experiment` (write)
- Python 3.11+ and [UV](https://docs.astral.sh/uv/)

## One-time setup

```bash
# Create experiment dataset (skip if it already exists)
bq mk --dataset --location=us-east4 \
  --description="DROP hash CA cleaning experiment" \
  example-gcp-project:drop_hash_experiment

cd analytics
uv venv .venv
uv pip install --python .venv/bin/python dbt-bigquery
cp profiles.yml.example profiles.yml   # or export DBT_PROFILES_DIR=$PWD
```

Optional: set `DBT_GCP_PROJECT` if not using `example-gcp-project`.

## Build CA non-name models

```bash
cd analytics
source .venv/bin/activate
dbt build --select tag:drop_clean_ca
```

Models are tagged `drop_clean_ca` and write to `drop_hash_experiment`:

| Model | Grain | Description |
|-------|-------|-------------|
| `stg_ca_person` | view | CA rows from `person_db.person` |
| `stg_ca_phones` | view | CA phones; prefers cell over land |
| `int_ca_email_hash` | `dwid, state` | Email std + Base64(SHA256) hash |
| `int_ca_phone_hash` | `dwid, state` | Phone std + hash |
| `int_ca_zip_hash` | `dwid, state` | ZIP std + hash |
| `int_ca_dob_hash` | `dwid, state` | DOB `YYYYMMDD` std + hash |

## Standardization rules (DROP v1.2.0, non-name)

- **Email:** remove all whitespace, lowercase; keep dots and plus signs
- **Phone:** strip non-digits; last 10 digits (or all if fewer than 10); cell preferred over landline
- **ZIP:** drop ZIP+4 extension; alphanumeric only; lowercase; strip leading zeros; first 5 characters
- **DOB:** parse to `YYYYMMDD`; unparseable → null std and hash
- **Hash:** `TO_BASE64(SHA256(std))` on UTF-8 string (BigQuery `SHA256` on STRING)

Official CPPA vectors are asserted by singular tests in `tests/assert_cppa_*_vector.sql` (literal inputs, no MDR PII).

## Future triggers

Documented entrypoint for schedulers: `dbt build --select tag:drop_clean_ca` (see plan `docs/plans/2026-07-17-001-feat-drop-hash-ca-cleaning-experiment-plan.md`).
