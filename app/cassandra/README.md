# Cassandra suppression

**Data-vertical suppression pipe** — writes idempotent suppressions to on-prem restricted-dwid tables via `cassandra_attempts` (`step=suppression` only). No matching routes.

## Insert contract

- `source_of_restriction` = **`Habeas`**
- `type_of_restriction` = **`person`**
- Minimal columns: `dwid` (bigint PK) + date/timestamp + source/type — no PII address/name fields by default

| Env | Endpoint | Qualified table |
|-----|----------|-----------------|
| Dev | `broker-db-dev.example.internal:9041` | `person_db_dev.restricted_person_id_worker` |
| Prod | `broker-db-prod.example.internal:9042` | `person_db.restricted_person_id` |

User `dprwrk`; passwords + SSL PEM in Secret Manager only.

## Runtime

- Package: `cassandra_worker` (not `cassandra` — that name is the CQL driver)
- `CASSANDRA_TRANSPORT=stub` (default) or `live`
- Live needs: `CASSANDRA_HOST`, `CASSANDRA_PORT`, `CASSANDRA_KEYSPACE`, `CASSANDRA_TABLE`, `CASSANDRA_USER`, `CASSANDRA_PASSWORD` or `_FILE`, `CASSANDRA_SSL_CA`
- `CASSANDRA_TABLE` defaults: `restricted_person_id_worker` when `CASSANDRA_PORT=9041`, else `restricted_person_id`
- Cloud Run must use Direct VPC egress → VPC `dpra` → Cloud NAT (see [`infra/README.md`](../../infra/README.md))

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
