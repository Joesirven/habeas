> inherits: ../AGENTS.md

# AGENTS.md — app/cassandra/

**Kind:** automation

Writes idempotent suppressions to restricted_person_id on on-prem Cassandra via Cloud VPN.


- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `cassandra_` or `matching_` as appropriate.
