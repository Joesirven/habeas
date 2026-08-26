# Cassandra suppression

**Data-vertical suppression pipe** — writes idempotent DWID restrictions to
on-prem restricted-dwid tables. The DWID is already matched by **Data Vertical
Matching** ([`app/matching/`](../matching/) against `drop_hash_index`). This
worker does not match, hash, or refresh an index.

Owner wizard: no method — INF provisioned; prod cassandra-prod stays stub / do-not-write.

Queue: `cassandra_attempts` (`step=suppression` only). Catalog binding: Data
vertical → system `cassandra` (empty `allowed_approaches`). Test vertical uses
the same slug as **System A** (placeholder), never as a live hash source.

## What this worker is not

- **No matching.** No `/matching/submit` or `/matching/collect` (404). Matching
  lives in [`app/matching/`](../matching/). `cassandra_attempts` CHECK is
  `step IN ('suppression')` only.
- **No hash mart.** Cassandra is **not** in `VERTICAL_HASH_REFRESH_SYSTEMS`.
  Core `validate_vertical_hash_system("cassandra")` rejects it. There is no
  `/hash-refresh/process` (404). Admin-api remaining-vertical hash-refresh /
  matching proxies do not include `cassandra`.
- **No dbt.** Do not add Cassandra models, sources, or hashed-raw tables under
  [`transform/external_hash/`](../../transform/external_hash/). Do not invent a
  `cassandra_email_hash` mart. DROP DWID lookup uses
  [`transform/drop_hash/`](../../transform/drop_hash/), not this app.
- **Not a live hash source in the owner wizard.** Hidden
  (`OWNER_WIZARD_HIDDEN_SYSTEM_ID = 'cassandra'`). Owner connector list skips
  it. Data vertical is catalog `view_only`. No invite, no credential fields, no
  Upload/Live cadence. Connection gate is `view_only`.

`data_fulfillment_dispatcher` writes a separate GCS DWID file for Data
fulfillment. This worker is the CQL insert path for the same DWID identity; it
does not call that dispatcher and that dispatcher does not call this worker.

## Live-write status — **dev-only** (2026-07-30)

Successful smoke insert validated the live path on **DEV only** (NAT egress
`203.0.113.10` → `broker-db-dev.example.internal:9041` / `person_db_dev.restricted_person_id_worker`).
Synthetic test row `dwid=9000000000001` verified. Prod (`:9042` /
`person_db.restricted_person_id`) stays documented but **not** live — keep
`CASSANDRA_TRANSPORT=live` only on cassandra-dev; **cassandra-prod remains stub /
do-not-write** until explicit cutover. Smoke VM `dpra-cassandra-smoke` may still
exist for ops testing.

## Insert contract

Suppression claims a `cassandra_attempts` row and reads the Data-vertical DWID
from `matched_external_id` (fallback `external_ref`). Empty DWID →
`submit_error` / `missing_dwid`. No hash lookup in this worker.

- `source_of_restriction` = **`Habeas`**
- `type_of_restriction` = **`person`**
- Minimal columns: `dwid` (bigint PK) + date/timestamp + source/type — no PII
  address/name fields by default

| Env | Endpoint | Qualified table |
|-----|----------|-----------------|
| Dev | `broker-db-dev.example.internal:9041` | `person_db_dev.restricted_person_id_worker` |
| Prod | `broker-db-prod.example.internal:9042` | `person_db.restricted_person_id` |

User `dprwrk`; passwords + SSL PEM in Secret Manager only.

## Runtime

- Package: `cassandra_worker` (not `cassandra` — that name is the CQL driver)
- `CASSANDRA_TRANSPORT=stub` (default) or `live`
- Live needs: `CASSANDRA_HOST`, `CASSANDRA_PORT`, `CASSANDRA_KEYSPACE`,
  `CASSANDRA_TABLE`, `CASSANDRA_USER`, `CASSANDRA_PASSWORD` or `_FILE`,
  `CASSANDRA_SSL_CA`
- `CASSANDRA_TABLE` defaults: `restricted_person_id_worker` when `CASSANDRA_PORT=9041`,
  else `restricted_person_id`
- Cloud Run must use Direct VPC egress → VPC `dpra` → Cloud NAT (see
  [`infra/README.md`](../../infra/README.md))
- Routes: `POST /suppression/submit`, `POST /suppression/collect`, `GET /healthz`,
  `GET /readyz`

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

```bash
uv run --package cassandra-worker pytest app/cassandra/tests -q
```

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
