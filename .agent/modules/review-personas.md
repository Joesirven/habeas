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
| QCQA | every required suite | testers did not **run** pytest / `bun test` — listing commands is not enough |
