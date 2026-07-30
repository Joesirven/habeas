> inherits: ../AGENTS.md

# AGENTS.md — app/cassandra/

**Kind:** automation

Data-vertical suppression pipe: writes idempotent suppressions to on-prem Cassandra
`restricted_person_id` over TLS (Cloud NAT static egress — see `infra/README.md`).

## Settled insert contract (2026-07-30)

MDR suppression owners confirmed:

| Field | Value |
|-------|--------|
| System of record | `restricted_person_id` (base MDR suppression list) |
| `source_of_restriction` | **`Habeas`** |
| `type_of_restriction` | **`person`** |
| Columns written | `dwid`, `date_of_restriction`, `insert_timestamp`, `source_of_restriction`, `type_of_restriction` only (no name/address unless owners change this) |

| Env | Host:port | Keyspace | Password secret |
|-----|-----------|----------|-----------------|
| Dev | `broker-db-dev.example.internal:9041` | `person_db_dev` (test copy pending from owners) | `cassandra-dprwrk-password-dev` |
| Prod | `broker-db-prod.example.internal:9042` | `person_db` | `cassandra-dprwrk-password-prod` |

Shared: user `dprwrk`, CA PEM secret `cassandra-ssl-ca-pem`.

## Worker rules

- Attempt queue: `cassandra_attempts` with `step IN ('suppression')` only — no matching step.
- Package import path is **`cassandra_worker`** (avoids shadowing PyPI `cassandra-driver`).
- Vendor vocabulary (`restricted_person_id`, Habeas/person) lives only in `adapters/restricted_person_id_adapter.py`.
- Transport: `CASSANDRA_TRANSPORT=stub` (default, tests) or `live` (requires secrets + NAT egress).
- Never log raw DWIDs, passwords, or PEM. Persist redacted `request_payload` on the attempt audit JSON only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `cassandra_`.
- Routes: `POST /suppression/submit`, `POST /suppression/collect` (+ healthz/readyz).
