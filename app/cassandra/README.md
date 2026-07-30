# Cassandra suppression

**Data-vertical suppression pipe** — writes idempotent suppressions to on-prem `restricted_person_id` via `cassandra_attempts` (`step=suppression` only). No matching routes and **no external hash index** (DROP hash matching stays in `transform/drop_hash` / data fulfillment).

Writes over **TLS** using INF-provided service account credentials and CA PEM. Egress is pinned through **Cloud NAT** static IPs for allowlisting (not Cloud VPN).

**Contact:** `broker-db-prod.example.internal:9042` · cluster `PERSON_DB_PROD_CLUSTER` · Cassandra 3.11.4 · TLS required · username `dprwrk` (password in Secret Manager only).

Cloud Run FastAPI worker exposes `/suppression/submit`, `/suppression/collect`, `/healthz`, `/readyz`. Stub adapter in `adapters/stub.py` — no live CQL in tests.

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Egress IPs + endpoint:** [`infra/README.md`](../../infra/README.md) — section *Cassandra egress — Cloud NAT*.

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
