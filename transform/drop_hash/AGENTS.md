# Agent guide — transform/drop_hash

Production dbt project for DROP hash-index serving tables in BigQuery.

## Scope

| Path | Role |
|------|------|
| `models/drop_clean/` | State-filtered staging + intermediate hashes (`var('state', 'CA')`) |
| `models/marts/` | Serving marts → `email_hash`, `phone_hash`, `ndz_hash` via build+swap |
| `udf/` | BigQuery JS `normalize_name` in `drop_hash_index` |
| `drop_normalize/` | Python DROP v1.2.0 standardization + CPPA vector tests |
| `compare/` | Experiment arm comparison (reads `drop_hash_experiment` only) |
| `macros/swap_serving_tables.sql` | Post-build rename swap for serving tables |

## Invariants

- Dataset: `drop_hash_index` (not `drop_hash_experiment`).
- No MDR PII in tests — CPPA vectors use literals only.
- Serving columns: `(hash, dwid, state)`; phone mart may have two rows per dwid (cell + land).
- Worker invokes dbt from this directory with `--vars '{state: ...}'`.

## Commands

```bash
cd transform/drop_hash
DBT_PROFILES_DIR=. dbt build --vars '{state: CA}'
cd drop_normalize && uv run pytest tests -q
```

## Do not

- Point production models at `drop_hash_experiment`.
- Commit `profiles.yml` or ADC secrets.
- Run raw `bq`/`psql` with PII in agent sessions without operator approval.

## Parent

Inherits repo root [AGENTS.md](../../AGENTS.md).
