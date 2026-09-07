# Data Vertical Matching

This app matches **all intake sources** against the **Data vertical** only.
Auth0, Axios Headquarters, and other vendor verticals are separate workers — not
this process. Webform / CSV / manual stay in this same app (MDR plaintext) — do
not add a second Cloud Run for those intakes. Target Cloud Run names:
`data-vertical-matching-dev` / `data-vertical-matching-prod` and drain jobs
`data-vertical-matching-drain-dev` / `data-vertical-matching-drain-prod`. **Prod**
is live: `data-vertical-matching-prod`; `admin-api-prod` `_MATCHING_URL` points
there (not legacy `matching-prod`). **Dev** may still run historical
`matching-dev` until Jose flips admin-api-dev to `data-vertical-matching-dev`.

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

## Chunk drain

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
6. **Prod:** live. Cloud SQL `dpra-prod` exists. `data-vertical-matching-prod` + Job
   `data-vertical-matching-drain-prod` are deployed; `admin-api-prod` `_MATCHING_URL`
   points at `https://data-vertical-matching-prod-hsa55rg7ja-uk.a.run.app` (not
   legacy `matching-prod`). Scheduler `dpra-prod-matching` → `/ensure-drain`.
   **Dev** may still run historical `matching-dev` + `matching-drain-dev` until
   Jose flips admin-api-dev to `data-vertical-matching-dev`.

## Auth0 vertical

**Canonical path:** the Auth0 worker (`app/auth0`) matches Email, Phone, and NDZ
against its own external_hash marts (`auth0_email_hash__build`,
`auth0_phone_hash__build`, `auth0_ndz_hash__build`) via `/matching/submit` and
upserts `request_vertical_matching`. See [`app/auth0/README.md`](../auth0/README.md).
Phone/NDZ vertical enqueue is gated by request-dispatcher
`DISPATCH_VERTICAL_LIST_TYPES` (Auth0, Axios HQ, `hr_alumni`, `bizdev_contacts` —
default Email-only until marts are ready).

**matching-dev side-path (legacy / email-focused):** historical drain code and
`Auth0HashPipeline` still reference the email mart only. Do not assume
matching-dev looks up Phone or NDZ Auth0 marts, and do not treat that side-path
as the source of truth for Auth0 phone/ndz matching. DROP drain itself stays
Data-vertical only.

Allowlisted audit keys on any Auth0 extras still include `auth0_match_count`,
`auth0_bq_dataset`, `auth0_error_code`. Never log hashes, vendor ids, or emails.

**Cadence is UNSET and out of scope.** Matching does **not** call `evaluate_connection_gate` or block when owner refresh cadence is missing.

**`auth0-dev` is not deployed.** Marts are filled by **local** Auth0 hash refresh —
[`app/auth0/README.md`](../auth0/README.md) § Auth0 matching on dev. Do not invent a Cloud Run Auth0 worker for that local path.

| Variable | Role |
|----------|------|
| `EXTERNAL_HASH_BQ_PROJECT` | BQ project for Auth0 marts (default `example-gcp-project`) |
| `EXTERNAL_HASH_BQ_DATASET` | Dataset (default `external_hash_index`) |
| `GCP_PROJECT` | Already required for chunk drain |

**IAM (Jose-gated):** any matching-dev SA that still reads the email side-path needs project `roles/bigquery.jobUser` and **table-level** `roles/bigquery.dataViewer` on `external_hash_index.auth0_email_hash__build` — not dataset-wide write. Auth0 worker mart reads (email / phone / NDZ) are owned by that worker’s identity — see [`app/auth0/README.md`](../auth0/README.md) and [`infra/README.md`](../../infra/README.md).

Dev path: (1) local Auth0 hash refresh until email/phone/ndz marts exist, (2) dispatch + Auth0 worker `/matching/submit` (not matching-dev for phone/ndz), (3) SELECT `request_vertical_matching` (`vertical=auth0`), (4) owner GET / PUT on admin-api — [`app/admin_api/README.md`](../admin_api/README.md) § Auth0 vertical.

## Local

```bash
uv sync --package matching-worker
uv run --package matching-worker uvicorn matching.main:app \
  --reload --app-dir app/matching/src --port 8084
```

Local `/process` and `/ensure-drain` are DROP Data-vertical only. Auth0
Email/Phone/NDZ matching runs on the Auth0 worker — see § Auth0 vertical.
Deployed DROP wave uses **matching-dev** / `data-vertical-matching-*`, not this process.

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
**Design:** `Projects/Data Privacy/01-ARCHITECTURE/Decisions/ADR-21-DROP-Hash-Matching.md` (Addendum, 2026-07-13) + `05-DELIVERABLES/Matching-Design-Brief.md` in the KB.
**Plan:** [`docs/plans/2026-07-22-001-feat-matching-chunk-drain-plan.md`](../../docs/plans/2026-07-22-001-feat-matching-chunk-drain-plan.md)
