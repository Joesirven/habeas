# External vertical hash index — dbt project

BigQuery [dbt](https://docs.getdbt.com/) project for **Tier-C / non–data-warehouse**
hash indexes. Materializes serving marts from **already-hashed** raw extracts written
by per-system hash-refresh workers for Auth0 (and other hashed-raw systems). Axios HQ
(`axios_headquarters`) is upload-every-batch, not a hashed-raw worker on this tree.

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
| Hashed raw | `external_hash_index.auth0_hashed_raw` | Worker-written; hash-only |
| Staging | `stg_auth0_hashed` | Thin select from source |
| Serving build | `auth0_email_hash__build` | `(hash_value, vendor_record_id, system, built_at)` |
| Serving | `auth0_email_hash` | Shared lookup table after build+swap |

Build+swap macros are documented in [macros/README.md](macros/README.md) (mirrors
`transform/drop_hash`); swap implementation is deferred to a follow-up unit.

### Serving schema (per system)

| Table | Columns | Clustering |
|-------|---------|------------|
| `{system}_email_hash` | `hash_value`, `vendor_record_id`, `system`, `built_at` | `(system, hash_value)` |

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

### Hashed-raw table contract (Jose / OQ1 only)

Workers write `{system}_hashed_raw` with hash columns only. Do not create these
tables in prod without approval. Same shape for every system in scope:

```sql
-- Jose / OQ1 only — do not run in prod without approval:
-- CREATE TABLE `example-gcp-project.external_hash_index.auth0_hashed_raw` (
--   email_hash STRING NOT NULL,
--   vendor_record_id STRING NOT NULL,
--   system STRING NOT NULL,
--   extracted_at TIMESTAMP NOT NULL
-- );
```

Repeat with `paylocity_hashed_raw`, `lever_hashed_raw`,
`hr_alumni_hashed_raw`, and `bizdev_contacts_hashed_raw`. Do **not** create
`axios_headquarters_hashed_raw` or invent `axios_hashed_raw` this slice.
No plaintext email.

## Build (manual refresh)

Hash-refresh workers will invoke dbt from this directory after writing hashed raw.
Until workers land, operators can run manually (requires live BigQuery + profiles):

```bash
cd transform/external_hash
DBT_PROFILES_DIR=. dbt build
```

Disable serving swap when macros exist: `--vars '{perform_serving_swap: false}'`.

Auth0 worker selects only its pair:

```bash
dbt build --select stg_auth0_hashed mart_auth0_email_hash
```

## Systems in scope

| System | Hashed raw | Mart | Hash refresh |
|--------|------------|------|--------------|
| Auth0 | `auth0_hashed_raw` | `mart_auth0_email_hash` (`auth0_email_hash__build`) | Yes |
| Axios HQ (`axios_headquarters`) | `axios_headquarters_hashed_raw` | `mart_axios_headquarters_email_hash` (`axios_headquarters_email_hash__build`) | Yes (upload CSV) |
| Paylocity | `paylocity_hashed_raw` | `mart_paylocity_email_hash` (`paylocity_email_hash__build`) | Yes |
| Lever | `lever_hashed_raw` | `mart_lever_email_hash` (`lever_email_hash__build`) | Yes |
| Alumni Google Sheet | `hr_alumni_hashed_raw` | `mart_hr_alumni_email_hash` (`hr_alumni_email_hash__build`) | Yes |
| Contact Us Google Sheet | `bizdev_contacts_hashed_raw` | `mart_bizdev_contacts_email_hash` (`bizdev_contacts_email_hash__build`) | Yes |
| Mailchimp | — | — | Retired (no dbt models) |
| Cassandra | — | — | No (suppress-only pipe) |

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
