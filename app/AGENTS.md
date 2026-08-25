> inherits: ../AGENTS.md

# AGENTS.md — app/

All Cloud Run FastAPI deployables. **Each app subdirectory has its own AGENTS.md and README.md.**

## Kinds

| Kind | Apps |
|------|------|
| **control_plane** | [`admin_api/`](admin_api/) |
| **automation** | [`matching/`](matching/), [`request_dispatcher/`](request_dispatcher/), [`reaper/`](reaper/), … |

## All apps (version 0)

[`admin_api/`](admin_api/) · [`matching/`](matching/) · [`request_dispatcher/`](request_dispatcher/) · [`drop_connector/`](drop_connector/) · [`drop_ingestor/`](drop_ingestor/) · [`hash_index_refresh/`](hash_index_refresh/) · [`data_fulfillment_dispatcher/`](data_fulfillment_dispatcher/) · [`reaper/`](reaper/) · [`sla_monitor/`](sla_monitor/) · [`cassandra/`](cassandra/) · [`paylocity/`](paylocity/) · [`lever/`](lever/) · [`auth0/`](auth0/) · [`google_sheets/`](google_sheets/)

## Rules

- Import `habeas-privacy-core` only — no cross-import between apps.
- No migrations inside apps — use [`db/migrations/`](../db/migrations/).
