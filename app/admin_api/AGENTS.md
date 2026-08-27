> inherits: ../AGENTS.md

# AGENTS.md — app/admin_api/

**Kind:** control_plane

Main control-plane FastAPI app. **Resource server** for web, CLI, and future clients. Dashboard, approvals, Server-Sent Events live stream, mutation routes.

**Identity (Architecture B — live on prod web):** Cloud Run Identity-Aware Proxy (IAP) is **off** on admin-api (`--no-iap`). `REQUIRE_IAP_IDENTITY=true` requires a **verified Bearer**. Header-alone (`X-Goog-Authenticated-User-Email` without a verified Bearer) is **401**. Legal `resolve_actor` sources: `user_jwt` (GIS user token, `aud` = OAuth client `IAP_OAUTH_CLIENT_ID`), `bearer_jwt` (ADC / Cloud Run `aud` = `ADMIN_API_ID_TOKEN_AUDIENCE`), `iap_header` (verified Bearer **plus** IAP email). A verified user token (`user_jwt`) uses the same role allowlists as the IAP-header-plus-Bearer path. ADC Cloud Run tokens (`bearer_jwt`) stay on the super_admin gate.

Humans use **admin-web IAP** as the SSO front door. Browser JSON is a Google Identity Services user Bearer on this API. Server-Sent Events stay same-origin `/api/live/events` (nginx mints a service-account Bearer and forwards IAP headers) — nginx SSE path unchanged. `admin-api-prod` invoker matches live `admin-api-dev` (`allUsers` + compute SA + `jsirven@`) so GIS reaches the app; the app still verifies the JWT. GIS JWT `aud` is the OAuth client, not this Cloud Run URL. CLI: `habeas-cli auth login --adc` or `auth login` — pin both `ADMIN_API_ID_TOKEN_AUDIENCE` and `IAP_OAUTH_CLIENT_ID`.

Do **not** re-enable Cloud Run IAP on admin-api. Do **not** re-run `infra/cloudbuild/admin-api-dev-iam.yaml`. Do **not** edit accepted SirvenOS architecture decision records from this repo.

- Routes: approvals, dashboard, admin rules, ops, `GET /live/events`
- Unified Runs: `GET /ops/runs` — filters `job`, `status`, `request_id`, `process_id`
  (bulk download attempt id; ingest/matching via download `gcs_uri`), `window`/`since`
- Ops logs: `GET /ops/logs` — project-level feed (worker attempt tables +
  `admin_audit_log`); filters `severity`, `resource`, `source`, `q`, `window`/`since`
  (Pipeline Errors = `severity=ERROR`; Logs = unfiltered). Severity filters push into
  SQL so ERROR/WARNING rows are not drowned by recent INFO audits. Planned Ops IA
  consolidation: `docs/plans/2026-07-30-005-feat-ops-command-center-ia-plan.md`.
- Identity: `GET /me` — `given_name`, `needs_connector_setup`,
  `assigned_vertical_labels`, `connector_reminders` (allowlisted codes; soft via
  `evaluate_connection_reminder` — never block login).
- Vertical-scoped connectors (shipped): super_admin `connections_admin` — catalog, assign
  owners, mode/cadence, test, wizard reset, delete (`GET/POST/DELETE /ops/connections`,
  `owner-candidates`). Owner wizard `owner_connectors` (`/owner/...`) — in-wizard creds+test,
  upload templates. **Connection-credential invite mint/redeem retired** —
  `POST .../invites` and revoke return **410 Gone**; assignment remains the grant
  for connection owners. `data_user` invite handlers exist
  (`GET/POST /connect/{token}`, `mint_member_invite`) but **`owner_router` is not
  mounted** — Team members mint is **not live** until that router is included.
  Do not claim teammate invites shipped.
- Matching **hard-gated** when Upload stale, Live rotation overdue, or wizard incomplete
  (`evaluate_connection_gate` / `evaluate_vertical_matching_gate`); UX Needs refresh /
  Action required — not Connected. Connecting ≠ matching/hash workers for that vertical.
  Auth0 `GET /requests/{request_id}/verticals/auth0/match-candidates` uses the same
  `evaluate_vertical_matching_gate` as matching (409 `gate_blocked` when not allowed).
  Audit counts + `gate_code` only.
- Secrets to Secret Manager (`dpra/connections/{system}/{connection_id}`); allowlisted
  `detail` only. Google Sheets SA in `metadata`. `data` vertical view-only in owner wizard.
  `DELETE /ops/connections/{id}` does not delete GSM secrets. Plan:
  `docs/plans/2026-08-11-001-feat-vertical-scoped-connectors-plan.md`.
- DROP ops: `GET /ops/drop/pipeline`, spine proxies, hash-index refresh enqueue /
  enqueue-all (USPS 50+DC) / process. Header/snapshot/matching-progress are cheap
  tickers — `GET /ops/drop/pipeline/summary`, `GET /ops/drop/console/snapshot`,
  `GET /ops/drop/matching-progress`: no `drop_raw_requests` spine; matching-progress
  is one `GROUP BY status` on `matching_attempts` only (no JOIN `requests`);
  sequential awaits on one asyncpg connection; `statement_timeout` 4s on those
  acquires. Prod hang on admin-api-prod-00078 was a DB stall (COUNT/JOIN over
  ~1.84M rows), not a missing route; `GET /me` stayed fast. Do not apply this
  budget to `GET /ops/drop/pipeline` full spine.
- Worker fleet discovery (shipped): `GET /ops/workers/fleet` — pull-based union of
  Cloud Scheduler + Cloud Run (DEV: `dpra-dev-*` / `*-dev`); health = existing
  `/readyz` probes; conventions in `habeas_privacy_core.fleet`. Schedules:
  `GET|PATCH /ops/workers/schedules`. Attempt-table browser:
  `GET /ops/workers/attempt-tables` (+ rows) with allowlisted columns/filters only.
  Web: `/ops/workers/settings` (single Settings surface). Naming: `infra/README.md`
  § Fleet discovery naming conventions.
- Fleet visibility (legacy rollup): `GET /ops/drop/workers`, `GET /ops/health/queues` —
  admin_api aggregates `/readyz` + Postgres depths; browser never calls workers
- Health Configuration (U24): `GET/PATCH /ops/health/retry-config` persists
  `ops_retry_config` overrides (floor 4); reaper merges on next `/reap` cycle;
  edited under Workers → Settings (UI), not a separate Health product.
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
- MDR people search: `GET /ops/drop/matching-contacts/search` (`q` min 2 chars, required
  2-letter `state` — 422 if missing, `limit` 1..20) — MDR `person`/`phones` (same contact
  shape as matching-result enrich). Role: `MatchingReviewPrincipal`. Data view-only —
  no owner cadence gate. Never log `q`, names, emails, phones, or DWIDs.
- Assign / escalate (U17): reuses `approval_requests` with `action_type=workflow.assignment`
  (no new migration) — `POST /ops/drop/workflow/assign`, `POST .../escalate`,
  `GET .../assignments`; targets `reviewer` | `legal` | `data_owner`; actor = IAP email
- Per-vertical dispositions (U1): `request_vertical_dispositions` is the source of
  record for the gates fulfillment reads — `GET /requests/{request_id}/dispositions`,
  `PUT /requests/{request_id}/dispositions/{vertical}` (`status` 3/4/5, `dwids`,
  `vendor_record_ids`, `early_advance`). Wave M `LIVE_VERTICALS` is `data` +
  `auth0` + `communications` + `people_hr`. Catalog systems **Axios HQ**
  (`axios_hq`), `lever`, and `paylocity` are treated live for write-gates
  (aliases → `communications` / `people_hr`) — not extra live write keys.
  Retracted slug `axios_headquarters` is **unknown** on disposition/kickoff
  write paths (not coming-soon). Coming-soon write keys (`cassandra`, `bizdev`)
  stay catalog-only and rejected on write. Mailchimp is retired from the
  catalog — not a coming-soon write vertical. Historical `tech` is an Auth0
  read alias, not a second live write key. Cassandra is **suppress-only** —
  no matching, hash-refresh, or dbt; keep it out of `LIVE_VERTICALS`. Status
  3/4 require a selection (`dwids` for `data`, defaulting to the matching
  result; `vendor_record_ids` for Auth0 / Communications / People/HR); status
  5 requires none. Matching promote upserts the `data` disposition and keeps
  `drop_raw_requests.response_status` in sync. Selected ids reach authorized
  callers only — audit records counts.
- Remaining verticals (Wave M): matching after a **mapped upload** (persist
  `column_mapping` + `gcs_uri` → existing hash-refresh → dbt mart → remaining
  matching enqueue). Super_admin
  `POST /ops/verticals/{system}/hash-refresh/enqueue|process` and
  `.../matching/enqueue|process`; candidates
  `GET /requests/{request_id}/verticals/{system}/match-candidates`. Allowlist
  `axios_headquarters`, `paylocity`, `lever`, `hr_alumni`, `bizdev_contacts`.
  Display Axios HQ; remaining-ops aliases `axios_hq` → worker slug
  `axios_headquarters`. Cassandra is **not** on that allowlist (404).
  matching-dev stays DROP-only — do not invent matching-dev vertical lookup.
  Worker URLs are settings-only; do not invent `*.run.app` hosts.
- Live connection fail: owner **Retry connection** or **Set up manual
  upload** until live is fixed in the wizard. Do not treat Lever
  `GET /v1/users` or Paylocity SFTP `listdir` as candidate extract (S01/S02
  **no-go**: [`tmp/lever-email-extract-research.md`](../../tmp/lever-email-extract-research.md),
  [`tmp/paylocity-email-extract-research.md`](../../tmp/paylocity-email-extract-research.md)).
  Do not invent Axios HTTP, Lever `/v1/opportunities`, Paylocity REST/SFTP
  parse, `axios_hashed_raw`, or CSV columns beyond existing templates +
  owner `column_mapping` headers.
- Journey fulfillment gates (plan `2026-07-29-001`): do **not** enqueue
  fulfillment solely from `matching.review` — require **Legal kickoff** per
  approved vertical; Access packs/notice require identity status + **required
  comment**; reject CA DROP typed as Access. See
  [`.agent/modules/privacy-invariants.md`](../../.agent/modules/privacy-invariants.md).
- Postgres LISTEN on approval events → forward to Server-Sent Events clients

- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `admin_` or `matching_` as appropriate.
- Mutations require authenticated identity (`REQUIRE_IAP_IDENTITY` on deployed API) + AuditMiddleware; matching-results payloads are ids/counts only (no PII). Cloud Run IAP stays **off** on admin-api.
