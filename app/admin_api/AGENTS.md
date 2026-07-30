> inherits: ../AGENTS.md

# AGENTS.md — app/admin_api/

**Kind:** control_plane

Main control-plane FastAPI app. Identity-Aware Proxy, dashboard, approvals, Server-Sent Events live stream, mutation routes for web and Habeas CLI.

- Routes: approvals, dashboard, admin rules, ops, `GET /live/events`
- Unified Runs: `GET /ops/runs` — filters `job`, `status`, `request_id`, `process_id`
  (bulk download attempt id; ingest/matching via download `gcs_uri`), `window`/`since`
- Ops logs: `GET /ops/logs` — project-level feed (worker attempt tables +
  `admin_audit_log`); filters `severity`, `resource`, `source`, `q`, `window`/`since`
  (Dashboard Errors = `severity=ERROR`; Logs = unfiltered). Planned Ops IA
  consolidation: `docs/plans/2026-07-30-005-feat-ops-command-center-ia-plan.md`.
- DROP ops: `GET /ops/drop/pipeline`, spine proxies, hash-index refresh enqueue /
  enqueue-all (USPS 50+DC) / process
- Fleet visibility (U23): `GET /ops/drop/workers`, `GET /ops/health/queues` —
  admin_api aggregates `/readyz` + Postgres depths; browser never calls workers
- Health Configuration (U24): `GET/PATCH /ops/health/retry-config` persists
  `ops_retry_config` overrides (floor 4); reaper merges on next `/reap` cycle
- Home summary: `GET /ops/drop/stats/global` (ids/counts only)
- Matching result detail includes attempt history + allowlisted `audit_payload`
- `POST /ops/drop/match` proxies matching worker `/process` (one row) and opens a
  pending `matching.review` gate on success
- Matching drain: `POST /ops/drop/ensure-drain` proxies matching `/ensure-drain`
  (starts Job when configured). Wave kick after `/ops/drop/dispatch` and after
  hash-index refresh process when rematch enqueued. Pipeline JSON includes
  `matching_attempts.drain` (active/holder/expires_at — ids/counts only)
- Matching results (Unit 8b / U15): `GET /ops/drop/matching-results` (list + global stats),
  filters: `match_type`, `q`/`request_id` (substring on uuid text), `state` (normalized
  `requests.requestor_state`), `recorded_after`/`recorded_before` (ISO date/datetime on
  latest `matching_results.recorded_at`). Stats stay **global** (`filters.stats_scope=global`);
  list items include `requestor_state` (2-letter only). Deadline / approaching-SLA list
  filters skipped — no deadline column without new schema.
  `GET /ops/drop/matching-results/{request_id}` (detail + attempt audit drill-down),
  `POST .../bulk-approve` (bulk promote), `POST .../bulk-decline`,
  `POST .../{request_id}/promote`, `POST .../{request_id}/decline`
- Assign / escalate (U17): reuses `approval_requests` with `action_type=workflow.assignment`
  (no new migration) — `POST /ops/drop/workflow/assign`, `POST .../escalate`,
  `GET .../assignments`; targets `reviewer` | `legal` | `data_owner`; actor = IAP email
- Journey fulfillment gates (plan `2026-07-29-001`): do **not** enqueue
  fulfillment solely from `matching.review` — require **Legal kickoff** per
  approved vertical; Access packs/notice require identity status + **required
  comment**; reject CA DROP typed as Access. See
  [`.agent/modules/privacy-invariants.md`](../../.agent/modules/privacy-invariants.md).
- Postgres LISTEN on approval events → forward to Server-Sent Events clients

- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `admin_` or `matching_` as appropriate.
- Mutations IAP-protected + AuditMiddleware; matching-results payloads are ids/counts only (no PII).
