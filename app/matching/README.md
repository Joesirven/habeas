# Data Vertical Matching

This app matches **all intake sources** against the **Data vertical** only.
Auth0, Axios Headquarters, and other vendor verticals are separate workers — not
this process. Webform / CSV / manual stay in this same app (MDR plaintext) — do
not add a second Cloud Run for those intakes. Target Cloud Run names:
`data-vertical-matching-dev` / `data-vertical-matching-prod` and drain jobs
`data-vertical-matching-drain-dev` / `data-vertical-matching-drain-prod`. Live
rename is Jose-gated; historical `matching-dev` may still be the running service
until cutover.

A `MatchingPipeline` interface with one adapter per source — `DropHashPipeline`
(DROP: SHA-256 compare against the BigQuery hash-index marts) and
`PlaintextMatchPipeline` (webform / CSV / manual: plaintext lookup against
**MDR**; mechanics not wired yet) — dispatched by a router keyed on
`IntakeSource`. Runtime today is DROP-only (`DropHashPipeline` +
`drop_hash_index` + chunk drain). A future state-specific matching requirement
is a new adapter class, not a new app.

## DROP hash lookup

- Looks up `hash_value` in `example-gcp-project.drop_hash_index` (`email_hash` / `phone_hash` /
  `ndz_hash`) with mandatory `state = @lookup_state` bound to the requester’s normalized
  `requestor_state` (never hardcode California; never return out-of-state DWIDs).
- Persists `MatchResult.match_count` and an allowlisted `audit_payload` JSONB on each attempt
  (adapter, duration, match_count, lookup_state, BQ tables, redacted errors — no hashes/dwids/PII).
- Reaper default `max_attempts` is **5** (≥3 retries after the initial attempt); Health
  Configuration may override via admin_api (floor 4).

## Chunk drain (Method E)

- Queue remains **one `matching_attempts` row per request**.
- Hot path: `POST /ensure-drain` acquires a single-flight `matching_drain_lease`, then
  starts Cloud Run Job **`data-vertical-matching-drain-dev`** (5 parallel tasks). Each task runs
  `python -m matching.chunk_drain` and drains **≤10K** homogeneous chunks via set-based
  BigQuery (`lookup_dwids_by_hashes`). Tasks compete with `SKIP LOCKED`.
- Job task HTTP unit (optional/ops): `POST /drain-chunk` (one chunk).
- Fallback: if `MATCHING_DRAIN_JOB_NAME` is unset, `/ensure-drain` runs the inline
  budgeted loop (`run_drain_budget`).
- Small path unchanged: `POST /process` (one claim). Sets `submitted_at` on `in_flight`
  so the reaper can recover hung rows.
- Wave kick: admin-api chains `/ensure-drain` after `/ops/drop/dispatch` and after
  hash-index refresh process when rematch enqueued. Catch-all: Scheduler →
  matching `POST /ensure-drain`.

### Compat-first cutover

1. Deploy matching + migration `matching_create_matching_drain_lease`.
2. Deploy Job via `data-vertical-matching-dev.yaml` (embeds Job deploy) or `data-vertical-matching-drain-job-dev.yaml`.
3. Confirm pending declines faster than ~12/hour (Job executions visible in Cloud Run).
4. Flip matching Scheduler to ensure-drain only.
5. Mid-flight rows: complete or reaper timeout → new pending → chunk drain.
6. **Prod:** Jose-approved (2026-07-22). Use `infra/cloudbuild/data-vertical-matching-prod.yaml` once
   prod Cloud SQL exists; create/flip `dpra-prod-matching` → `/ensure-drain` after smoke.
   Today `example-gcp-project` has no prod SQL / `data-vertical-matching-prod` runtime — live
   rename is Jose-gated; historical `matching-dev` + `matching-drain-dev` may still be
   the running services until cutover.

## Auth0 vertical

After a successful **DROP email** match (v1; phone / NDZ skip this step), `matching-dev` and the local worker / chunk drain look up `example-gcp-project.external_hash_index.auth0_email_hash__build` (`system = 'auth0'`) and upsert `request_vertical_matching` (`vertical=auth0`, opaque `vendor_record_id`s, `match_count`). Same cycle as DROP — not a second `matching_attempts` row and not `app/auth0` stub `/matching/submit`.

Auth0 lookup failure is **non-fatal** to the DROP attempt. Allowlisted audit keys only: `auth0_match_count`, `auth0_bq_dataset`, `auth0_error_code`. Never log hashes, vendor ids, or emails.

**Cadence is UNSET and out of scope.** Matching does **not** call `evaluate_connection_gate` or block when owner refresh cadence is missing.

**`auth0-dev` is not deployed.** The mart is filled by **local** Auth0 hash refresh — [`app/auth0/README.md`](../auth0/README.md) § Auth0 matching on dev. Do not invent a Cloud Run Auth0 worker.

| Variable | Role |
|----------|------|
| `EXTERNAL_HASH_BQ_PROJECT` | BQ project for the Auth0 mart (default `example-gcp-project`) |
| `EXTERNAL_HASH_BQ_DATASET` | Dataset (default `external_hash_index`) |
| `GCP_PROJECT` | Already required for chunk drain |

**IAM (Jose-gated):** matching-dev runtime SA needs project `roles/bigquery.jobUser` and **table-level** `roles/bigquery.dataViewer` on `external_hash_index.auth0_email_hash__build` — not dataset-wide write (Mailchimp shares `external_hash_index`). See [`infra/README.md`](../../infra/README.md) (matching-dev + Auth0 mart).

Dev path: (1) local hash refresh until the mart has rows, (2) DROP dispatch / `/ops/drop/ensure-drain` on **matching-dev**, (3) SELECT `request_vertical_matching` (`vertical=auth0`), (4) owner GET / PUT on admin-api — [`app/admin_api/README.md`](../admin_api/README.md) § Auth0 vertical.

## Local

```bash
uv sync --package matching-worker
uv run --package matching-worker uvicorn matching.main:app \
  --reload --app-dir app/matching/src --port 8084
```

Local `/process` and `/ensure-drain` run the same Auth0 lookup when a DROP email attempt succeeds (needs ADC + mart IAM on the caller). Deployed wave uses **matching-dev**, not this process.

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
**Design:** `Projects/Data Privacy/01-ARCHITECTURE/Decisions/ADR-21-DROP-Hash-Matching.md` (Addendum, 2026-07-13) + `05-DELIVERABLES/Matching-Design-Brief.md` in the KB.
**Plan:** [`docs/plans/2026-07-22-001-feat-matching-chunk-drain-plan.md`](../../docs/plans/2026-07-22-001-feat-matching-chunk-drain-plan.md)
