> inherits: ../AGENTS.md

# AGENTS.md — app/admin_api/

**Kind:** control_plane

Main control-plane FastAPI app. **Resource server** for web, CLI, and future clients. Dashboard, approvals, Server-Sent Events live stream, mutation routes.

**Identity (Architecture B — intended, not live on prod web):** Cloud Run Identity-Aware Proxy (IAP) is **off** on admin-api (`--no-iap`). `REQUIRE_IAP_IDENTITY=true` requires a **verified Bearer**. Header-alone (`X-Goog-Authenticated-User-Email` without a verified Bearer) is **401**. Legal `resolve_actor` sources: `user_jwt` (GIS user token, `aud` = OAuth client `IAP_OAUTH_CLIENT_ID`), `bearer_jwt` (ADC / Cloud Run `aud` = `ADMIN_API_ID_TOKEN_AUDIENCE`), `iap_header` (verified Bearer **plus** IAP email). A verified user token (`user_jwt`) uses the same role allowlists as the IAP-header-plus-Bearer path. ADC Cloud Run tokens (`bearer_jwt`) stay on the super_admin gate.

Humans use **admin-web IAP** as the SSO front door. **Intended B** browser JSON is a Google Identity Services user Bearer on this API. **Current prod web is not on B:** live 100% is `admin-web-prod-00023-fnz` (nginx `/api`, SA Bearer + IAP headers). Revision **00024** is the unused B bake at **0%** — do not flip until GIS `/me` is proven on DEV. Do not claim prod already uses GIS. Server-Sent Events stay same-origin `/api/live/events` (nginx mints a service-account Bearer and forwards IAP headers). `allUsers` `run.invoker` is **stripped** on `admin-api-prod` and `admin-api-dev` (remaining: compute SA + `jsirven@`). GIS JWT `aud` is the OAuth client, not this Cloud Run URL — Cloud Run IAM would reject GIS unless `allUsers`, which is off. A 00024 flip today would **403** at IAM (or **401** if `allUsers` were on but GIS fail-soft). Do not say `allUsers` stays so GIS can reach the API. Cloud Build admin-api yamls: `--no-allow-unauthenticated`, `--no-iap`, `REQUIRE_IAP_IDENTITY=true`, fail-closed `allUsers` strip (not `|| true`). CLI: `habeas-cli auth login --adc` or `auth login` — pin both `ADMIN_API_ID_TOKEN_AUDIENCE` and `IAP_OAUTH_CLIENT_ID`.

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
  enqueue-all (USPS 50+DC) / process
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
  `vendor_record_ids`, `early_advance`). `LIVE_VERTICALS` is `data` + `auth0`. Coming-soon write
  keys (**Axios HQ** `axios_headquarters`, `lever`, `paylocity`, `cassandra`,
  `communications`, `people_hr`, `bizdev`) are catalog-only and rejected on
  write. Mailchimp is retired from the catalog — not a coming-soon write
  vertical. Historical `tech` is an Auth0 read alias, not a second live write
  key. Status 3/4 require a selection (`dwids` for `data`, defaulting to the
  matching result; `vendor_record_ids` for `auth0`); status 5 requires none.
  Matching promote upserts the `data` disposition and keeps
  `drop_raw_requests.response_status` in sync. Selected ids reach authorized
  callers only — audit records counts.
- Journey fulfillment gates (plan `2026-07-29-001`): do **not** enqueue
  fulfillment solely from `matching.review` — require **Legal kickoff** per
  approved vertical; Access packs/notice require identity status + **required
  comment**; reject CA DROP typed as Access. See
  [`.agent/modules/privacy-invariants.md`](../../.agent/modules/privacy-invariants.md).
- Postgres LISTEN on approval events → forward to Server-Sent Events clients

- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `admin_` or `matching_` as appropriate.
- Mutations require authenticated identity (`REQUIRE_IAP_IDENTITY` on deployed API) + AuditMiddleware; matching-results payloads are ids/counts only (no PII). Cloud Run IAP stays **off** on admin-api.
