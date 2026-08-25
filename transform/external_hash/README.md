# External vertical hash index — dbt project

BigQuery [dbt](https://docs.getdbt.com/) project for **Tier-C / non–data-warehouse**
hash indexes. Materializes serving marts from **already-hashed** raw extracts written
by per-system hash-refresh workers (Mailchimp, Paylocity, Lever, Auth0, Google Sheets).

**GCP project:** `example-gcp-project` · **Dataset (default):** `external_hash_index` · **Region:** `us-east4`

> **OQ1 (deferred):** Confirm the production dataset name with Jose before first prod apply.

## Privacy invariant

**Sources are already hashed.** Extract workers hash identifiers in memory (DROP v1.2.0 /
CPPA rules) and persist only hashed values plus opaque vendor ids to BigQuery.

This dbt project must **never**:

- Reference plaintext email, phone, name, DOB, ZIP, or other PII columns
- Add models that standardize or hash raw vendor fields (hashing happens upstream)
- Land vendor PII into Habeas BigQuery “like MDR”

Allowed source columns: `*_hash` fields, `vendor_record_id`, `system`, `extracted_at`,
and other non-PII metadata agreed per system.

## Architecture

```text
hash-refresh worker (in-memory hash) → BQ hashed raw → dbt staging → dbt mart → serving swap
```

| Layer | Example | Notes |
|-------|---------|-------|
| Hashed raw | `external_hash_index.mailchimp_hashed_raw`, `external_hash_index.auth0_hashed_raw` | Worker-written; hash-only |
| Staging | `stg_mailchimp_hashed`, `stg_auth0_hashed` | Thin select from source |
| Serving build | `mailchimp_email_hash__build`, `auth0_email_hash__build` | `(hash_value, vendor_record_id, system, built_at)` |
| Serving | `mailchimp_email_hash`, `auth0_email_hash` | Shared lookup table after build+swap |

Build+swap macros are documented in [macros/README.md](macros/README.md) (mirrors
`transform/drop_hash`); swap implementation is deferred to a follow-up unit.

### Serving schema (per system)

| Table | Columns | Clustering |
|-------|---------|------------|
| `mailchimp_email_hash` | `hash_value`, `vendor_record_id`, `system`, `built_at` | `(system, hash_value)` |
| `auth0_email_hash` | `hash_value`, `vendor_record_id`, `system`, `built_at` | `(system, hash_value)` |

`hash_value` is Base64(SHA-256) of the DROP-standardized identifier. Matching workers
join DROP request hashes to these marts; suppression uses `vendor_record_id` only.

## Prerequisites

- [Google Cloud SDK](https://cloud.google.com/sdk) with Application Default Credentials
- BigQuery read/write on `example-gcp-project.external_hash_index` (dataset may not exist until first prod apply)
- dbt-bigquery (see one-time setup)

## One-time setup

```bash
# Dataset creation deferred until OQ1 confirmed — example:
# bq mk --dataset --location=us-east4 \
#   --description="External vertical hash index (hashed raw + serving marts)" \
#   example-gcp-project:external_hash_index

cd transform/external_hash
uv venv .venv
uv pip install --python .venv/bin/python dbt-bigquery

# Copy profiles from drop_hash as a template, then edit dataset to external_hash_index:
cp ../drop_hash/profiles.yml.example profiles.yml
# Edit profile name to external_hash and dataset to external_hash_index
```

## Build (manual refresh)

The Auth0 hash-refresh worker invokes this select after writing hashed raw.
Worker env, enqueue, and `POST /hash-refresh/process`:
[app/auth0/README.md](../../app/auth0/README.md). Mailchimp and other vertical
workers are still scaffold. Operators may also run the Auth0 select manually
when `auth0_hashed_raw` is present (requires live BigQuery + profiles):

```bash
cd transform/external_hash
DBT_PROFILES_DIR=. dbt parse
DBT_PROFILES_DIR=. dbt build
# Auth0 subset (after auth0_hashed_raw is loaded):
DBT_PROFILES_DIR=. dbt build --select stg_auth0_hashed mart_auth0_email_hash
```

Disable serving swap when macros exist: `--vars '{perform_serving_swap: false}'`.

## Systems in scope

| System | Hashed raw | Mart | Hash refresh |
|--------|------------|------|--------------|
| Mailchimp | `mailchimp_hashed_raw` | `mart_mailchimp_email_hash` | Yes |
| Paylocity | (future) | (future) | Yes |
| Lever | (future) | (future) | Yes |
| Auth0 | `auth0_hashed_raw` | `mart_auth0_email_hash` | Yes |
| Google Sheets | (future) | (future) | Yes |
| Cassandra | — | — | No (suppress-only pipe) |

## Auth0

Email hash index only (no phone or NDZ). The auth0 hash-refresh worker runs
the Management API users-export job (`POST /api/v2/jobs/users-exports`),
hashes emails in memory (DROP v1.2.0 / CPPA), and writes **hash-only** rows
to BigQuery. dbt never sees plaintext email. Extract path:
[app/auth0/README.md](../../app/auth0/README.md).

Same layering as Mailchimp: hashed raw → staging view → serving-build mart.

| Layer | Name | Role |
|-------|------|------|
| Hashed raw (source) | `external_hash_index.auth0_hashed_raw` | Worker-written; declared in `models/sources.yml` |
| Staging | `stg_auth0_hashed` | Thin view; drops null `email_hash` |
| Serving build | `mart_auth0_email_hash` → alias `auth0_email_hash__build` | Distinct `(hash_value, vendor_record_id, system, built_at)`; clustered `(system, hash_value)` |
| Serving | `auth0_email_hash` | Planned swap target (`macros/README.md`; deferred) |

`vendor_record_id` is the opaque Auth0 `user_id` (vendor vocabulary stays in
`app/auth0/adapters/`). `system` is always `auth0`. Users without a hashable
email are skipped by the worker and must not appear as null-`email_hash` rows.

### Hashed-raw table contract

Mirror Mailchimp `mailchimp_hashed_raw`. Allowed columns only — no plaintext
email, name, phone, or other profile fields.

| Column | Type | Notes |
|--------|------|-------|
| `email_hash` | STRING | Base64(SHA-256) of DROP-standardized email |
| `vendor_record_id` | STRING | Opaque Auth0 `user_id` |
| `system` | STRING | Always `auth0` |
| `extracted_at` | TIMESTAMP | Worker write time |

There is no standalone DDL file in this project; apply the following in BigQuery
only after OQ1 (dataset name confirmed) and Jose approval for production.

```sql
-- Hashed identifiers only. Do not add plaintext email or profile columns.
CREATE TABLE `example-gcp-project.external_hash_index.auth0_hashed_raw` (
  email_hash STRING NOT NULL,
  vendor_record_id STRING NOT NULL,
  system STRING NOT NULL,
  extracted_at TIMESTAMP NOT NULL
)
OPTIONS (
  description = "Auth0 Management hashed extract (email_hash + opaque user_id). Populated by the auth0 hash-refresh worker."
);
```

Dataset creation remains deferred until OQ1 (see commented `bq mk` under
One-time setup). Do not create the production dataset or table without Jose
approval.

### Build Auth0 marts

Requires live BigQuery, `profiles.yml` (gitignored), and a loaded
`auth0_hashed_raw` table. Hash-refresh workers invoke the same select after
writing hashed raw.

```bash
cd transform/external_hash
DBT_PROFILES_DIR=. dbt parse
DBT_PROFILES_DIR=. dbt build --select stg_auth0_hashed mart_auth0_email_hash
```

Matching reads `auth0_email_hash__build` until serving swap lands.

## Worker contract

Auth0 is live (extract → hash in memory → BQ hashed raw → dbt). Other systems remain scaffold:

```bash
cd transform/external_hash
dbt build
# Auth0: dbt build --select stg_auth0_hashed mart_auth0_email_hash
```

Matching workers query serving marts by `(hash_value, system)`; vendor vocabulary stays
in each app’s `adapters/`.

## Parent

Repo map and invariants: [AGENTS.md](AGENTS.md) · root [AGENTS.md](../../AGENTS.md).
