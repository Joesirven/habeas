# Agent guide — data-privacy

Code repo for **Habeas Data Privacy Request Automation**. Design authority (architecture decisions, version 0 spec): `~/Documents/SirvenOS/Habeas/Projects/Data Privacy/`.

**Bitbucket:** `dsts/data-privacy` · **Branch:** `master` for integration; agent work on `agent/<slug>`.

**Atlassian:** always **`acli`** for Jira / Confluence / admin — never `gh` or the broken Python `bb` package. See [`.agent/modules/atlassian-acli.md`](.agent/modules/atlassian-acli.md).

---

## Session start

1. Read this file.
2. Read `AGENTS.md` in the directory you will edit (`> inherits` chain).
3. Load `.agent/modules/<name>.md` only when a gate below matches — just-in-time, not all at once.

---

## Repo map (layout v4)

| Path | Role |
|------|------|
| [`libs/habeas-privacy-core/`](libs/habeas-privacy-core/) | Shared library — models, queue, audit, adapter bases (not deployed alone) |
| [`transform/drop_hash/`](transform/drop_hash/) | dbt + UDF DROP hash index — prod home; serving marts `email_hash` / `phone_hash` / `ndz_hash` in `example-gcp-project.drop_hash_index` (not `analytics/`) |
| [`transform/external_hash/`](transform/external_hash/) | dbt marts for external vertical hash indexes (Auth0, Axios HQ, Paylocity, Lever, Sheets, …) — hashed raw only; Axios HQ (`axios_headquarters`) is upload-every-batch |
| [`app/`](app/) | All Cloud Run FastAPI apps — control plane + automation |
| [`app/matching/`](app/matching/) | Matching worker + chunk drain; Python package stays `matching`; Job target `data-vertical-matching-drain-*` via `/ensure-drain`. **Prod** uses `data-vertical-matching-prod` (`admin-api-prod` `_MATCHING_URL`). **Dev** cutover from legacy `matching-dev` is still Jose-gated. |
| [`app/admin_api/`](app/admin_api/) | Main control-plane app — mutations, dashboard, live events |
| [`app/auth0/`](app/auth0/) | Auth0 worker — matching/suppression + hash refresh into [`transform/external_hash`](transform/external_hash/) |
| [`clients/web/`](clients/web/) | Admin web app — Vite, React, TypeScript, Bun; Ops Dashboard (Pipeline / Errors / Logs / Health) + connections onboarding |
| [`clients/cli/habeas-cli/`](clients/cli/habeas-cli/) | Habeas command-line — hybrid read/write |
| [`db/migrations/`](db/migrations/) | Unified database migrations (dbmate) |
| [`infra/`](infra/) | Cloud Build, Terraform, Docker |
| [`scripts/`](scripts/) | One-off ops scripts — not imported by production code |
| [`.agent/modules/`](.agent/modules/) | Repeatable workflows — load on gate match only |

**Python:** [UV](https://docs.astral.sh/uv/) only — `uv sync`, `uv run`, `uv lock`. Workspace members: `libs/*`, `app/*`, `clients/cli/*`. Never pip, venv, or poetry in this repo.

---

## Orchestration

Master agent **plans → delegates executors → separate reviewers → merges**. Disjoint file ownership per subagent. Large outputs go to `tmp/`, referenced by path.

If multi-file task → read [`.agent/modules/orchestration.md`](.agent/modules/orchestration.md).  
If pre-merge → read [`.agent/modules/review-personas.md`](.agent/modules/review-personas.md).

---

## Module gates (just-in-time)

| If you are… | Read |
|-------------|------|
| Touching Jira / Confluence / PRs / merge / Atlassian | [`atlassian-acli.md`](.agent/modules/atlassian-acli.md) |
| Editing Python | [`python-uv.md`](.agent/modules/python-uv.md) |
| Editing `db/migrations/` | [`db-migrations.md`](.agent/modules/db-migrations.md) |
| Deploy / prod migrate / CLI `--execute` | [`prod-write-gate.md`](.agent/modules/prod-write-gate.md) |
| Editing `clients/web/` | [`frontend-stack.md`](.agent/modules/frontend-stack.md) |
| Any UI / visual design | [`design-taste.md`](.agent/modules/design-taste.md) |
| DROP Ops IA UI (Runs / Requests / ops dashboard / request journey workbench) | [`design-taste-ops-ia.md`](.agent/modules/design-taste-ops-ia.md) |
| Agent using Habeas CLI | [`cli-agent-interface.md`](.agent/modules/cli-agent-interface.md) |
| Touching request or audit tables | [`privacy-invariants.md`](.agent/modules/privacy-invariants.md) |

---

## Vocabulary

| Term | Meaning |
|------|---------|
| **request** | One privacy request (a person asked Habeas to act). |
| **source** | Where the request arrived — **CA DROP**, access portal, authorized agent, manual. Not a connection. |
| **system** (connection) | A data system in a vertical (Alumni Google Sheet, Axios HQ). Owner verifies matching **per system**. |
| **vertical** | Org slice that owns systems (People/HR, Communications, **Test vertical**). |
| **batch** | Intake grouping, typically date + source (e.g. `Aug 21 · CA DROP`). |
| **matching-review item** | One review row for a request **in one system**. |
| **data owner** | Configures the vertical and its connections. |
| **data user** | Reviews, fulfills, and refreshes matching in assigned verticals. |

**CA DROP is a source**, never a system or connection chip. **Test vertical** systems display as **System A** / **System B** (placeholders). Other verticals show the real connection name.

## Invariants

- No personally identifiable information in logs or audit payloads.
- **Mutations** only through `app/admin_api` (web and command-line write path).
- Deployed admin-api requires authenticated identity (`REQUIRE_IAP_IDENTITY=true`): a **verified Bearer** Google ID token. `resolve_actor` rejects IAP email header alone (header-alone → 401). Legal sources: `user_jwt` (GIS, `aud` = OAuth client), `bearer_jwt` (ADC / Cloud Run `aud`), `iap_header` (verified Bearer **plus** IAP email). CLI: `habeas-cli auth login --adc` (super_admin) or `auth login` (IAP); pin both `ADMIN_API_ID_TOKEN_AUDIENCE` and `IAP_OAUTH_CLIENT_ID` — see `infra/README.md` and [`.agent/modules/cli-agent-interface.md`](.agent/modules/cli-agent-interface.md). Never call workers directly; never grant user→worker `run.invoker`.
- Command-line **SELECT-only** for ad-hoc analysis — no insert, update, delete, truncate.
- No production writes without Jose approval.
- No secrets in git.
- **snake_case** for directories and Python packages; **no acronyms** in agent files — spell terms out on first use.
- Do not duplicate knowledge-base content here — link to SirvenOS project folder.

---

## Prod status (2026-08-25)

On `example-gcp-project`: Cloud SQL `dpra-prod`, Secret Manager `database-url-prod`, and the DROP spine plus vertical workers are live — `admin-api-prod` (`_MATCHING_URL` → `data-vertical-matching-prod`, not legacy `matching-prod`; `max-instances=3`), `drop-connector-prod`, `drop-ingestor-prod`, `request-dispatcher-prod`, `data-vertical-matching-prod`, `hash-index-refresh-prod`, `data-fulfillment-dispatcher-prod`, `drop-notice-dispatcher-prod`, `reaper-prod`, and vertical workers `auth0-prod`, `axios-headquarters-prod`, `hr-alumni-prod`, `bizdev-contacts-prod`, `lever-prod`, `paylocity-prod` (retired unified `google-sheets-prod`).

**DROP intake (complete):** first production CA DROP pull finished (~1.84M requests); Data-vertical matching is complete. Ops orchestration used `POST /ops/drop/prod/confirm-run` (admin-api spine: connector download → ingestor land/promote → dispatch → ensure-drain) — that is the cutover runbook endpoint, not an open blocker. Ongoing pulls use scheduled `drop-connector-prod` `/download`.

**Live pipeline cards (push-driven):** DROP pipeline live cards on `GET /live/events` are commit-triggered — trigger `drop_bulk_process_stats_notify` on `drop_bulk_process_stats` → `pg_notify('drop_bulk_stats_changed', download_id)` → admin-api LISTEN bridge (`live_rollup_notify.BulkRollupBroadcaster`) → SSE `bulk_process` snapshot. Coalesce window `LIVE_BULK_NOTIFY_COALESCE_MS` (default 200ms), immediate flush when a batch's matching completes; shared 5s poll backstop runs once per process (replacing per-connection bulk polls, which survive only as an import-failure fallback); per-connection `matching_progress` 1.5s poll and all event shapes unchanged (no web client changes).

**Still off in prod:** Cassandra (`cassandra-prod` stays stub / do-not-write). Mailchimp is retired (Communications vertical is Axios HQ). **Prod web is on Architecture B (GIS)** — `admin-web-prod.yaml` bakes `VITE_ADMIN_API_URL=https://admin-api-prod-hsa55rg7ja-uk.a.run.app`; OAuth client id is baked from GSM `iap-oauth-client-id` at deploy (not in git). Browser GIS user JWT → `admin-api-prod` (app verifies `aud` = OAuth client). nginx `/api` remains for SSE. `admin-api-prod` invoker matches live `admin-api-dev` (`allUsers` + compute SA + `jsirven@`) so GIS Bearer passes Cloud Run IAM; app-level `REQUIRE_IAP_IDENTITY` still verifies the JWT. No ad-hoc production writes without Jose.

Runbook: [`infra/README.md`](infra/README.md) § Prod Cloud SQL + DROP cutover. Worker attach: [`app/AGENTS.md`](app/AGENTS.md).

---

## Do not

- Run raw SQL or `psql` in agent sessions — use Habeas CLI wrappers.
- Add a top-level `adapters/` or `utils/` directory.
- Edit accepted architecture decision records in the knowledge base from this repo.
- Commit credentials, `.env`, or connection strings.

---

## Commands

```bash
uv sync --all-packages
uv run --group dev pytest
uv run --package habeas-cli habeas-cli version
uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir app/admin_api/src
cd clients/web && bun install && bun run dev
dbmate -d db/migrations up
```
