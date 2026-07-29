# transform/access_export

dbt project for the **access reproduction (data subject access request) export layer**
in BigQuery — KTD-13 in
[`docs/plans/2026-07-21-001-feat-fulfillment-access-suppression-plan.md`](../../docs/plans/2026-07-21-001-feat-fulfillment-access-suppression-plan.md).
Sibling of [`drop_hash/`](../drop_hash/) (hash index); do not fold the two together.

## What it does

Models the privacy-install mapped `person_db` tables available today into
versioned, tested marts that the fulfillment access export
(`app/data_fulfillment_dispatcher`) reads when producing a requester's flat-file
pack on GCS.

| Layer | Dataset | Contents |
|-------|---------|----------|
| staging | `access_export_stg` | Thin passthrough views over `person_db` sources |
| marts | `access_export` | `dim_person`, `dim_vote_history`, `dim_district`, `dim_phones`, `fct_ballots`, `dim_analytics_continuous`, `dim_models` (+ `dbt_updated_at` provenance) |

Pending source grants (CEE_*, analytics_cyclic/frozen/retired, ProductionDatasets
freezes) join as new staging + marts when loaded — see the plan's table map.

## Commands

```bash
cd transform/access_export
cp profiles.yml.example profiles.yml   # once; gitignored

DBT_PROFILES_DIR=. dbt build                       # views (no raw-table copy)
DBT_PROFILES_DIR=. dbt build --vars '{mart_materialization: table}'  # clustered tables
DBT_PROFILES_DIR=. dbt test
```

Default mart materialization is **view** so builds cost nothing to create;
promote to `table` (clustered `(state, dwid)`) when per-request export pruning
matters. Every mart carries `dwid` / `state` not-null tests; `dim_person` has a
`(dwid, state)` uniqueness test.

## Fulfillment wiring

`data_fulfillment_dispatcher` defaults to raw `person_db` tables. Point it at
these marts with environment variables (no code change):

```
ACCESS_EXPORT_BQ_DATASET=access_export
ACCESS_EXPORT_BQ_TABLES=dim_person,dim_vote_history,dim_district,dim_phones,fct_ballots,dim_analytics_continuous,dim_models
```

Export artifacts land under `gs://privacy-fulfillment-dev/bulk-run/...` and are
deleted by the bucket's 30-day lifecycle rule
([`infra/gcs/privacy-fulfillment-lifecycle.json`](../../infra/gcs/privacy-fulfillment-lifecycle.json)).
