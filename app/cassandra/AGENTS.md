> inherits: ../AGENTS.md

# AGENTS.md — app/cassandra/

**Kind:** automation

Data-vertical suppression pipe: writes idempotent suppressions to on-prem Cassandra
`restricted_person_id` over TLS (Cloud NAT static egress — see `infra/README.md`). Matching for
the data vertical uses DROP hash / CEPI, not this worker.

- Attempt queue: `cassandra_attempts` with `step IN ('suppression')` only — no matching step.
- No hash-index refresh on this worker (no vendor PII extract; DWID suppress only).
- Routes: `POST /suppression/submit`, `POST /suppression/collect` (+ healthz/readyz).
- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `cassandra_`.
- Credentials and SSL PEM: Secret Manager only — never log PII or raw credentials.
