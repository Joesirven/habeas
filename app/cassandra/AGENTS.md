> inherits: ../AGENTS.md

# AGENTS.md — app/cassandra/

**Kind:** automation

Data-vertical **suppression-only** pipe: writes idempotent DWID restrictions to
on-prem Cassandra restricted-dwid tables over TLS (Cloud NAT static egress —
see `infra/README.md`).

The DWID is produced by **Data Vertical Matching** (`app/matching/` against
`drop_hash_index`), not by this worker. Catalog: Data vertical binds system
`cassandra` with empty `allowed_approaches`. Test vertical reuses the slug as
**System A** (placeholder).

## Not a hash worker — do not invent

- **No matching.** Do not add `/matching/submit` or `/matching/collect`.
  `cassandra_attempts` CHECK is `step IN ('suppression')` only.
- **No hash mart.** Cassandra is not in `VERTICAL_HASH_REFRESH_SYSTEMS`. Do not
  enqueue `vertical_hash_refresh_attempts` for `system=cassandra`. Do not add
  `/hash-refresh/process`.
- **No dbt.** Do not add Cassandra models, sources, or hashed-raw tables under
  `transform/external_hash/`. Do not invent a Cassandra serving mart. DROP DWID
  lookup stays in `transform/drop_hash/` + `app/matching/`.
- **Not an owner-wizard live hash source.** Keep it hidden
  (`OWNER_WIZARD_HIDDEN_SYSTEM_ID = 'cassandra'`). Do not add Live/Upload
  approaches, invite credentials, or hash-refresh cadence for this system. Data
  vertical stays catalog `view_only`.

`data_fulfillment_dispatcher` writes a GCS DWID file; this worker is the CQL
insert path. Do not cross-import those apps.

## Live-write status (2026-07-30) — **dev-only**

Live suppression inserts are **validated on DEV only**. Do **not** enable prod
live writes until an explicit cutover. **cassandra-prod stays stub /
do-not-write.**

| Fact | Detail |
|------|--------|
| Validated | 2026-07-30 from NAT egress **`203.0.113.10`** |
| Target | `broker-db-dev.example.internal:9041` → `person_db_dev.restricted_person_id_worker` |
| Insert shape | `dwid` + `date_of_restriction` + `insert_timestamp` + `source_of_restriction=Habeas` + `type_of_restriction=person` |
| Smoke row | Synthetic `dwid=9000000000001` verified |
| Prod | `broker-db-prod.example.internal:9042` / `person_db.restricted_person_id` is documented but **not enabled** for live writes |
| Transport | Keep `CASSANDRA_TRANSPORT=live` **only** for cassandra-dev; prod stays `stub` / do-not-write until cutover |
| Ops smoke VM | `dpra-cassandra-smoke` may still exist for ops testing |

## Settled insert contract (2026-07-30)

MDR suppression owners confirmed:

| Field | Value |
|-------|--------|
| System of record (prod) | `person_db.restricted_person_id` |
| System of record (dev) | `person_db_dev.restricted_person_id_worker` (empty clone; `dprwrk` write access) |
| `source_of_restriction` | **`Habeas`** |
| `type_of_restriction` | **`person`** |
| Columns written | `dwid`, `date_of_restriction`, `insert_timestamp`, `source_of_restriction`, `type_of_restriction` only (no name/address unless owners change this) |

| Env | Host:port | Keyspace | Table | Password secret |
|-----|-----------|----------|-------|-----------------|
| Dev | `broker-db-dev.example.internal:9041` | `person_db_dev` | `restricted_person_id_worker` | `cassandra-dprwrk-password-dev` |
| Prod | `broker-db-prod.example.internal:9042` | `person_db` | `restricted_person_id` | `cassandra-dprwrk-password-prod` |

Shared: user `dprwrk`, CA PEM secret `cassandra-ssl-ca-pem`.

## Worker rules

- Attempt queue: `cassandra_attempts` with `step IN ('suppression')` only — no
  matching step. Claim DWID from `matched_external_id` (fallback `external_ref`);
  empty DWID → `submit_error`. Do not look up hashes here.
- Package import path is **`cassandra_worker`** (avoids shadowing PyPI
  `cassandra-driver`).
- Vendor vocabulary (restricted-dwid tables, Habeas/person) lives only in
  `adapters/restricted_person_id_adapter.py`.
- Table: `CASSANDRA_TABLE` (or Settings `cassandra_table`); defaults
  `restricted_person_id_worker` when port=9041, else `restricted_person_id`.
- Transport: `CASSANDRA_TRANSPORT=stub` (default, tests) or `live` (requires
  secrets + NAT egress).
- Never log raw DWIDs, passwords, or PEM. Persist redacted `request_payload` on
  the attempt audit JSON only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `cassandra_`.
- Routes: `POST /suppression/submit`, `POST /suppression/collect` (+
  healthz/readyz). Matching and hash-refresh paths must stay 404.
