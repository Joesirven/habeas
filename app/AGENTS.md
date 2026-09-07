> inherits: ../AGENTS.md

# AGENTS.md — app/

All Cloud Run FastAPI deployables. **Each app subdirectory has its own AGENTS.md and README.md.**

## Kinds

| Kind | Apps |
|------|------|
| **control_plane** | [`admin_api/`](admin_api/) |
| **automation** | [`matching/`](matching/) (Data Vertical Matching), [`request_dispatcher/`](request_dispatcher/), [`reaper/`](reaper/), … |

## All apps (version 0)

[`admin_api/`](admin_api/) · [`matching/`](matching/) · [`request_dispatcher/`](request_dispatcher/) · [`drop_connector/`](drop_connector/) · [`drop_ingestor/`](drop_ingestor/) · [`hash_index_refresh/`](hash_index_refresh/) · [`data_fulfillment_dispatcher/`](data_fulfillment_dispatcher/) · [`reaper/`](reaper/) · [`sla_monitor/`](sla_monitor/) · [`cassandra/`](cassandra/) · [`axios_headquarters/`](axios_headquarters/) · [`paylocity/`](paylocity/) · [`lever/`](lever/) · [`auth0/`](auth0/) · [`hr_alumni/`](hr_alumni/) · [`bizdev_contacts/`](bizdev_contacts/)

Communications uses [`axios_headquarters/`](axios_headquarters/). Do not create duplicate Axios HQ workers elsewhere. Web connection create uses catalog id `axios_hq`; core catalog and attempts table use `axios_headquarters`.

## Prod vertical workers (2026-08-25)

Deployed on `example-gcp-project`: `auth0-prod`, `axios-headquarters-prod`, `hr-alumni-prod`, `bizdev-contacts-prod`, `lever-prod`, `paylocity-prod`, `drop-notice-dispatcher-prod`. Retired unified `google-sheets-prod` — see stub [`google_sheets/README.md`](google_sheets/README.md). Cassandra stays off prod. Deploy via `infra/cloudbuild/axios-headquarters-prod.yaml`.

**External hash matching:** Vertical workers match DROP Email / Phone / NDZ against
per-kind marts (`{system}_{email,phone,ndz}_hash__build`). Hashed raw + dbt home:
[`transform/external_hash`](../transform/external_hash/). Dispatch stays Email-only
until cutover — see [`request_dispatcher/`](request_dispatcher/).

## Rules

- Import `habeas-privacy-core` only — no cross-import between apps.
- No migrations inside apps — use [`db/migrations/`](../db/migrations/).
