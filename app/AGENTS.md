> inherits: ../AGENTS.md

# AGENTS.md — app/

All Cloud Run FastAPI deployables. **Each app subdirectory has its own AGENTS.md and README.md.**

## Kinds

| Kind | Apps |
|------|------|
| **control_plane** | [`admin_api/`](admin_api/) |
| **automation** | [`matching/`](matching/), [`mailchimp/`](mailchimp/), [`reaper/`](reaper/), … |

## All apps (version 0)

[`admin_api/`](admin_api/) · [`matching/`](matching/) · [`cassandra/`](cassandra/) · [`mailchimp/`](mailchimp/) · [`paylocity/`](paylocity/) · [`lever/`](lever/) · [`auth0/`](auth0/) · [`google_sheets/`](google_sheets/) · [`reaper/`](reaper/) · [`sla_monitor/`](sla_monitor/) · [`intake_csv_dispatcher/`](intake_csv_dispatcher/) · [`intake_drop_poller/`](intake_drop_poller/)

## Rules

- Import `habeas-privacy-core` only — no cross-import between apps.
- No migrations inside apps — use [`db/migrations/`](../db/migrations/).
