> inherits: ../AGENTS.md

# AGENTS.md — app/cassandra/

**Kind:** automation

Writes idempotent suppressions to `restricted_person_id` on on-prem Cassandra over TLS. Outbound traffic uses Cloud Run Direct VPC egress → VPC `dpra` → Cloud NAT static IPs (dev/prod). See [`infra/README.md`](../../infra/README.md).


- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `cassandra_` or `matching_` as appropriate.
- Credentials and SSL PEM: Secret Manager only — never log PII or raw credentials.
