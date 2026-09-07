# Agent guide — transform/external_hash

dbt project for external vertical hash-index serving tables in BigQuery.

## Scope

| Path | Role |
|------|------|
| `models/sources.yml` | Hashed raw BQ sources only (no plaintext PII tables) |
| `models/staging/` | Thin selects from hashed raw (`stg_*_hashed`) |
| `models/marts/` | Serving builds → `(hash_value, vendor_record_id, system, built_at)` — email, phone, and ndz per system |
| `macros/README.md` | Planned build+swap pattern (mirrors `drop_hash`) |

## Phone / NDZ cutover

Each in-scope system has email, phone, and ndz serving marts
(`mart_{system}_{email,phone,ndz}_hash`). Widen request-dispatcher enqueue only after
those marts are verified: set `DISPATCH_VERTICAL_LIST_TYPES=Email,Phone,NDZ` on
request-dispatcher (default remains Email-only). Order and rationale:
[README.md](README.md) § Phone/NDZ cutover order.

## Invariants

- **Canonical dbt home:** this directory (`transform/external_hash/`).
- **Dataset (default):** `example-gcp-project.external_hash_index` — confirm with Jose before prod (OQ1).
- **Hash-in-worker:** identifiers are hashed in the extract worker; BigQuery hashed raw and
  all dbt models reference **only** pre-hashed columns and opaque vendor ids.
- **No plaintext models:** never add staging/intermediate models that read `email`,
  `phone`, `name`, `dob`, `zip`, or equivalent vendor PII fields. If a new column is
  needed, extend the worker’s hashed raw schema — not dbt.
- Serving columns: `(hash_value, vendor_record_id, system, built_at)`; clustered
  `(system, hash_value)`.
- Cassandra is **suppress-only** — no hash refresh or dbt models for that system.
- No prod dbt runs or dataset creation without Jose approval.

## Commands

```bash
cd transform/external_hash
cp ../drop_hash/profiles.yml.example profiles.yml   # edit profile + dataset; gitignored
DBT_PROFILES_DIR=. dbt parse                        # structure check when profiles exist
DBT_PROFILES_DIR=. dbt build                        # requires live BQ + hashed raw data
```

## Do not

- Add models that reference plaintext PII columns.
- Commit `profiles.yml` or ADC secrets.
- Run production dbt without operator approval.
- Duplicate DROP hash-index logic here — reuse worker/core hashing; dbt only versions marts.

## Parent

Inherits repo root [AGENTS.md](../../AGENTS.md).
