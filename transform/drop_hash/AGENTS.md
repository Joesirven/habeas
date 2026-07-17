# Agent guide — transform/drop_hash

Production dbt project for DROP hash-index serving tables in BigQuery.

## Scope

| Path | Role |
|------|------|
| `models/drop_clean/` | State-filtered staging + intermediate hashes (`var('state', 'CA')`) |
| `models/marts/` | Serving marts → `email_hash`, `phone_hash`, `ndz_hash` via build+state merge |
| `udf/` | BigQuery JS `normalize_name` in `drop_hash_index` (bake-off winner) |
| `drop_normalize/` | Python DROP v1.2.0 standardization + CPPA vector tests |
| `macros/swap_serving_tables.sql` | Post-build state-scoped merge into serving tables |

## Invariants

- **Canonical dbt home:** this directory (`transform/drop_hash/`). Do not run production
  dbt from `analytics/` (legacy experiment tree on pre-migration branches).
- Dataset: `example-gcp-project.drop_hash_index` — serving tables `email_hash`, `phone_hash`,
  `ndz_hash` (not `drop_hash_experiment`).
- No MDR PII in tests — CPPA vectors use literals only.
- Serving columns: `(hash_value, dwid, state, built_at)`; clustered `(state, hash_value)`.
- Phone mart: two rows per dwid when both cell and land exist.
- Worker invokes dbt from this directory with `--vars '{state: ...}'` per state.
  Shared marts are filled for all MDR/DROP-served states (USPS 50+DC allowlist
  until Jose confirms Q6). Default `state: CA` in `dbt_project.yml` is local
  convenience only — production passes the attempt’s state.
- UDF body must stay the bake-off winner (`normalizeName` + LATIN_EXTENDED).

## Commands

```bash
cd transform/drop_hash
cp profiles.yml.example profiles.yml   # once; gitignored
DBT_PROFILES_DIR=. dbt build --vars '{state: CA}'
DBT_PROFILES_DIR=. dbt build --vars '{state: NY}'   # another state into shared marts
cd drop_normalize && uv run pytest tests -q
```

## Do not

- Run production hash-index dbt from `analytics/` or treat that path as the operator entrypoint.
- Point production models at `drop_hash_experiment`.
- Commit `profiles.yml` or ADC secrets.
- Run raw `bq`/`psql` with PII in agent sessions without operator approval.
- Truncate the bake-off UDF (missing LATIN_EXTENDED breaks accent folding in BQ JS).

## Parent

Inherits repo root [AGENTS.md](../../AGENTS.md).
