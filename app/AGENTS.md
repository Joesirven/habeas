> inherits: ../AGENTS.md

# AGENTS.md — app/

All Cloud Run FastAPI deployables. **Each app subdirectory has its own AGENTS.md and README.md.**

## Kinds

| Kind | Apps |
|------|------|
| **control_plane** | [`admin_api/`](admin_api/) |
| **automation** | [`matching/`](matching/), [`request_dispatcher/`](request_dispatcher/), [`mailchimp/`](mailchimp/), [`reaper/`](reaper/), … |

## All apps (version 0)

[`admin_api/`](admin_api/) · [`matching/`](matching/) · [`request_dispatcher/`](request_dispatcher/) **(U8)** · [`drop_connector/`](drop_connector/) **(CA DROP, U6)** · [`drop_ingestor/`](drop_ingestor/) **(CA DROP, U7)** · [`reaper/`](reaper/) · [`sla_monitor/`](sla_monitor/) · [`cassandra/`](cassandra/) · [`mailchimp/`](mailchimp/) · [`paylocity/`](paylocity/) · [`lever/`](lever/) · [`auth0/`](auth0/) · [`google_sheets/`](google_sheets/)

## Rules

- Import `habeas-privacy-core` only — no cross-import between apps.
- No migrations inside apps — use [`db/migrations/`](../db/migrations/).
