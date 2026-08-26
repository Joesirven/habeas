# module: review-personas

> Gate: before merge of any multi-file change.

Spawn **reviewer** subagents (not the same agent that implemented). Match change type:

| Change touches | Reviewer focus |
|----------------|----------------|
| auth, Identity-Aware Proxy, secrets | security |
| SQL, migrations, queue logic | migration + data correctness |
| matching / suppression outcomes | data quality |
| request or audit payloads | privacy |
| AGENTS.md, README, modules | documentation |
| clients/web | user experience |
| any production path | security + privacy minimum |

Push back with sourced notes in the diff or `tmp/` review file — do not merge on unresolved privacy or security findings.

## Testing quality-control / quality-assurance

For any multi-file or production-path change, quality-control / quality-assurance (QCQA) personas **must execute** hermetic tests — not only read code. Code-read-only QCQA is a **priority-zero (P0) process failure**.

UV, packages, and session gates: root [`AGENTS.md`](../../AGENTS.md) — do not copy that file here.

Each QCQA persona writes `/tmp/qcqa-<persona>-<slug>.md` with the commands run and pass/fail. Fail the QCQA round if a required suite fails or the invariants below regress.

Hermetic pytest: `DATABASE_URL=""`. Run every suite the change touches (at least one persona must run each required command). Testers must **run** the reaper suite and `test_vertical_chunk_drain.py` — listing them is not enough:

```bash
DATABASE_URL="" uv run --package drop-ingestor pytest app/drop_ingestor/tests/test_land.py -q
DATABASE_URL="" uv run --package drop-connector pytest app/drop_connector/tests/test_download.py -q
DATABASE_URL="" uv run --package request-dispatcher pytest app/request_dispatcher/tests/test_dispatch.py -q
DATABASE_URL="" uv run --package admin-api pytest app/admin_api/tests/test_drop_pipeline.py app/admin_api/tests/test_auth0_matching_api.py -q
DATABASE_URL="" uv run --package matching-worker pytest app/matching/tests/test_chunk_drain_job.py app/matching/tests/test_vertical_chunk_drain.py -q
DATABASE_URL="" uv run --package reaper pytest app/reaper/tests/test_reaper_health.py app/reaper/tests/test_reaper_config.py -q
cd clients/web && bun test
```

| Area | Suite | Fail the round if |
|------|--------|-------------------|
| drop-ingestor | `test_land.py` | Cloud Run `file://` does not raise `local_zip_unreachable`, or raises `FileNotFoundError` on `/tmp/drop_connector` |
| drop-connector | `test_download.py` | `K_SERVICE` + empty bucket does not yield `intake_gcs_bucket_required` |
| request-dispatcher | `test_dispatch.py` | Auth0/Email SQL lacks `$n::varchar` |
| admin-api | `test_drop_pipeline.py`, `test_auth0_matching_api.py` | health cache regresses; master data repository (MDR) search missing; Auth0 search not gated |
| admin-api | `test_drop_pipeline.py` (when those tests exist) | 404 undeployed is treated as worker down |
| admin-api | `test_drop_pipeline.py` | `GET /ops/drop/matching-progress` missing, or its SQL scans `drop_raw_requests` (must be one `GROUP BY status` on `matching_attempts` only) |
| admin-api | `test_drop_pipeline.py` | `intake_drop_poller` is in `WORKER_KEYS` or the pipeline chip |
| matching | `test_chunk_drain_job.py`, `test_vertical_chunk_drain.py` | matching review `INSERT` lacks `$1::varchar` (`AmbiguousParameterError` class); drain-job or vertical drain invariants regress |
| reaper | `test_reaper_health.py`, `test_reaper_config.py` | testers did not **run** the suite; matching reap or review reconcile regresses; fulfill is invoked |
| `clients/web` | `bun test` | web tests fail when `clients/web` changed |
| `clients/web` first-paint | `cd clients/web && bun test src/lib/admin-api-auth.test.ts` | first-paint GETs (`/me`, connectors list, snapshot or processes, pipeline header) lack the 8s `OPS_FAST_QUERY_TIMEOUT_MS`; prod probe budgets (`OPS_PROD_PROBE_MAX_MS` 5s, `OPS_ME_PROD_MAX_MS` 2s) regress; collapsed pipeline batch rows blank status/date/counts the API returned |
| admin-api live page-load | `DATABASE_URL="" uv run --package admin-api pytest app/admin_api/tests/test_drop_pipeline.py -k prod_page_load -q` (skips without `ADMIN_API_PROBE_URL` + token) | serving `GET /me` > 2s; `GET /owner/verticals/tech/connectors`, `GET /ops/drop/pipeline/summary`, or `GET /ops/drop/processes?days=7&intake_source=drop&limit=50` > 5s (or 8s SPA abort); `snapshot.processes` is `[]` while processes API has rows; GIS web (`admin-web-prod-00024`) at 100% |
| QCQA | every required suite | testers did not **run** pytest / `bun test` — listing commands is not enough |

## Page-load ship gate

Fail the QCQA round and **HOLD ship** when any of these are true (do not flip GIS; do not grant `allUsers`):

1. First paint / critical GET exceeds **5s** on the prod probe, or the SPA 8s abort fires. Named serving probes that **must** stay under 5s: `GET /owner/verticals/tech/connectors`, `GET /ops/drop/pipeline/summary`, `GET /ops/drop/processes?days=7&intake_source=drop&limit=50`.
2. Serving API `GET /me` exceeds **2s**.
3. Collapsed pipeline batch rows render with no status / date / counts when the API returned those fields (`collapsedBulkRowDisplay` + `admin-api-auth.test.ts`).
4. `GET /ops/drop/console/snapshot` returns empty `processes` while `GET /ops/drop/processes` has rows (blank collapsed pipeline batches).
5. `listOwnerConnectors` lacks the 8s `OPS_FAST_QUERY_TIMEOUT_MS` abort.
6. GIS web is at **100%** (`admin-web-prod-00024` or `ADMIN_WEB_GIS_TRAFFIC_PERCENT=100`).

Live probe env (skip the live tests when unset): `ADMIN_API_PROBE_URL`, `ADMIN_API_PROBE_TOKEN` (or `ADMIN_API_ID_TOKEN` / `CLOUD_RUN_ID_TOKEN`), optional `ADMIN_API_PROBE_EMAIL` / `IAP_USER_EMAIL`, optional `ADMIN_WEB_GIS_TRAFFIC_PERCENT`.
