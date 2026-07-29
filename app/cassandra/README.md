# Cassandra suppression

Writes idempotent suppressions to `restricted_person_id` on on-prem Cassandra over **TLS**, using INF-provided service account credentials and CA PEM. Egress is pinned through **Cloud NAT** static IPs for allowlisting (not Cloud VPN).

**Contact:** `broker-db-prod.example.internal:9042` · cluster `PERSON_DB_PROD_CLUSTER` · Cassandra 3.11.4 · TLS required.

Cloud Run FastAPI app (scaffold pending). Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Egress IPs + endpoint:** [`infra/README.md`](../../infra/README.md) — section *Cassandra egress — Cloud NAT*.

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
