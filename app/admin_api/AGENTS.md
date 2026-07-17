> inherits: ../AGENTS.md

# AGENTS.md — app/admin_api/

**Kind:** control_plane

Main control-plane FastAPI app. Identity-Aware Proxy, dashboard, approvals, Server-Sent Events live stream, mutation routes for web and Habeas CLI.

- Routes: approvals, dashboard, admin rules, ops, `GET /live/events`
- Postgres LISTEN on approval events → forward to Server-Sent Events clients
- DROP ops mutations (`/ops/drop/*`) are Identity-Aware Proxy–protected in deploy and audited via `AuditMiddleware`

- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `admin_` or `matching_` as appropriate.
