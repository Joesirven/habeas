# External vertical hash index — dbt project

BigQuery [dbt](https://docs.getdbt.com/) project for **Tier-C / non–data-warehouse**
hash indexes. Materializes serving marts from **already-hashed** raw extracts written
by per-system hash-refresh workers (Auth0, Paylocity, Lever, Sheets, …) and by the
Axios HQ upload path. Axios HQ (`axios_headquarters`) is **upload-every-batch** and
still lands hashed-raw (`axios_headquarters_hashed_raw`) — feed differs; contract does
not.

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
| Serving build | `auth0_email_hash__build` (also phone/ndz) | `(hash_value, vendor_record_id, system, built_at)` |
| Serving | `auth0_email_hash` (also phone/ndz) | Shared lookup table after build+swap |

Build+swap macros are documented in [macros/README.md](macros/README.md) (mirrors
`transform/drop_hash`); swap implementation is deferred to a follow-up unit.

### Serving schema (per system)

| Table | Columns | Clustering |
|-------|---------|------------|
| `{system}_email_hash` | `hash_value`, `vendor_record_id`, `system`, `built_at` | `(system, hash_value)` |
| `{system}_phone_hash` | same | same |
| `{system}_ndz_hash` | same | same |

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
--   email_hash STRING,
--   phone_hash STRING,
--   ndz_hash STRING,
--   vendor_record_id STRING NOT NULL,
--   system STRING NOT NULL,
--   extracted_at TIMESTAMP NOT NULL
-- );
```

Repeat with `paylocity_hashed_raw`, `lever_hashed_raw`,
`hr_alumni_hashed_raw`, and `bizdev_contacts_hashed_raw`. Do **not** invent
`axios_hashed_raw` (wrong name). Do **not** create
`axios_headquarters_hashed_raw` via this Jose DDL path — the Axios HQ worker
create-on-write / upload path owns that table (it is still hashed-raw).
No plaintext email.

## Build (manual refresh)

Hash-refresh workers will invoke dbt from this directory after writing hashed raw.
Until workers land, operators can run manually (requires live BigQuery + profiles):

```bash
cd transform/external_hash
DBT_PROFILES_DIR=. dbt build
```

Disable serving swap when macros exist: `--vars '{perform_serving_swap: false}'`.

Auth0 worker selects its staging + email/phone/ndz marts:

```bash
dbt build --select stg_auth0_hashed mart_auth0_email_hash mart_auth0_phone_hash mart_auth0_ndz_hash
```

## Systems in scope

| System | Hashed raw | Marts (email / phone / ndz builds) | Hash refresh |
|--------|------------|--------------------------------------|--------------|
| Auth0 | `auth0_hashed_raw` | `mart_auth0_{email,phone,ndz}_hash` | Yes |
| Axios HQ (`axios_headquarters`) | `axios_headquarters_hashed_raw` | `mart_axios_headquarters_{email,phone,ndz}_hash` | Yes (upload CSV) |
| Paylocity | `paylocity_hashed_raw` | `mart_paylocity_{email,phone,ndz}_hash` | Yes |
| Lever | `lever_hashed_raw` | `mart_lever_{email,phone,ndz}_hash` | Yes |
| Alumni Google Sheet | `hr_alumni_hashed_raw` | `mart_hr_alumni_{email,phone,ndz}_hash` | Yes |
| Contact Us Google Sheet | `bizdev_contacts_hashed_raw` | `mart_bizdev_contacts_{email,phone,ndz}_hash` | Yes |
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

## Phone/NDZ cutover order

Widen hashed_raw → hash-refresh with phone/ndz → dbt build marts → verify
non-empty (or Jose-approved empty) → set
`DISPATCH_VERTICAL_LIST_TYPES=Email,Phone,NDZ` on request-dispatcher → then
drain. Default remains Email-only so a dispatcher deploy does not enqueue
~1.2M Phone/NDZ before marts are ready.
