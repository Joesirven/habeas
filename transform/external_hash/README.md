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
| Hashed raw | `external_hash_index.mailchimp_hashed_raw` | Worker-written; hash-only |
| Staging | `stg_mailchimp_hashed` | Thin select from source |
| Serving build | `mailchimp_email_hash__build` | `(hash_value, vendor_record_id, system, built_at)` |
| Serving | `mailchimp_email_hash` | Shared lookup table after build+swap |

Build+swap macros are documented in [macros/README.md](macros/README.md) (mirrors
`transform/drop_hash`); swap implementation is deferred to a follow-up unit.

### Serving schema (per system)

| Table | Columns | Clustering |
|-------|---------|------------|
| `mailchimp_email_hash` | `hash_value`, `vendor_record_id`, `system`, `built_at` | `(system, hash_value)` |

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

Hash-refresh workers will invoke dbt from this directory after writing hashed raw.
Until workers land, operators can run manually (requires live BigQuery + profiles):

```bash
cd transform/external_hash
DBT_PROFILES_DIR=. dbt build
```

Disable serving swap when macros exist: `--vars '{perform_serving_swap: false}'`.

## Systems in scope

| System | Hashed raw | Staging | Serving mart(s) | Hash refresh |
|--------|------------|---------|-----------------|--------------|
| Mailchimp | `mailchimp_hashed_raw` | `stg_mailchimp_hashed` | `mailchimp_email_hash` | Yes |
| Paylocity | `paylocity_hashed_raw` | `stg_paylocity_hashed` | `paylocity_email_hash`, `paylocity_phone_hash` | Yes |
| Lever | `lever_hashed_raw` | `stg_lever_hashed` | `lever_email_hash` | Yes |
| Auth0 | `auth0_hashed_raw` | `stg_auth0_hashed` | `auth0_email_hash` | Yes |
| Google Sheets | `google_sheets_hashed_raw` | `stg_google_sheets_hashed` | `google_sheets_email_hash` | Yes |
| Cassandra | — | — | — | No (suppress-only pipe) |

### Per-system manual refresh

After a hash-refresh worker writes hashed raw, build that system's marts only:

```bash
cd transform/external_hash
DBT_PROFILES_DIR=. dbt build --select tag:system_mailchimp
DBT_PROFILES_DIR=. dbt build --select tag:system_paylocity
DBT_PROFILES_DIR=. dbt build --select tag:system_lever
DBT_PROFILES_DIR=. dbt build --select tag:system_auth0
DBT_PROFILES_DIR=. dbt build --select tag:system_google_sheets
```

Workers invoke the same `--select tag:system_<name>` after BQ load (swap macros deferred).

## Worker contract

Per-system hash-refresh worker flow (stub/live extract → hash in memory → BQ hashed raw → dbt):

```bash
cd transform/external_hash
dbt build
```

Matching workers query serving marts by `(hash_value, system)`; vendor vocabulary stays
in each app’s `adapters/`.

## Parent

Repo map and invariants: [AGENTS.md](AGENTS.md) · root [AGENTS.md](../../AGENTS.md).
