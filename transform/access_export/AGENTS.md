# Agent guide — transform/access_export

dbt project for access reproduction marts (KTD-13). See [README.md](README.md)
for layout and commands; design authority is
`docs/plans/2026-07-21-001-feat-fulfillment-access-suppression-plan.md`.

## Invariants

- Datasets: staging → `example-gcp-project.access_export_stg`, marts →
  `example-gcp-project.access_export` (custom `generate_schema_name`).
- Every mart keeps raw source columns intact plus `dbt_updated_at`; the
  fulfillment export filters `WHERE CAST(dwid AS STRING) IN UNNEST(@dwids) AND
  state = @lookup_state`, so `dwid` and `state` must survive staging untouched.
- Default mart materialization is `view` (no national-table copy). Promote with
  `--vars '{mart_materialization: table}'` — tables cluster `(state, dwid)`.
- No MDR PII in tests or seeds.
- Do not fold into `transform/drop_hash/` (separate cadence and grants).
- Commit neither `profiles.yml` nor credentials.

## Parent

Inherits repo root [AGENTS.md](../../AGENTS.md).
