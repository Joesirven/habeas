---
title: "External vertical hash indexes + per-system match/suppress workers"
date: 2026-07-30
type: feat
topic: external-vertical-hash-workers
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

## Goal Capsule

Stand up the Tier-C / non–data-warehouse verticals for California DROP with the session-settled pattern: **hash in the worker (never persist plaintext PII) → write hashed raw to BigQuery → dbt versioned builds into serving marts → per-system Cloud Run workers own matching and suppression via `step` on per-system attempt tables.**

**Systems in scope (from External-Integrations + app scaffolds):** Mailchimp (Marketing), Paylocity (HR), Lever (HR recruiting), Auth0 (Tech), Google Sheets (ad-hoc), Cassandra `restricted_person_id` (Data suppression pipe — suppress-only). Data-vertical DROP hash index (`transform/drop_hash`) and CEPI/Vertica remain out of this plan’s write scope.

**Authority:** ADR-11 (per-system worker) > ADR-08 (queue-as-table / `step`) > ADR-21 (DROP hash matching) > External-Integrations.md > Schema-Mailchimp-Attempts template > session-settled 2026-07-30 (hash-in-worker; hashed raw only; dbt for mart versioning; same bounded context for match+suppress).

**Stop when:** attempt tables + reaper registration exist; each match/suppress system has FastAPI submit/collect routes by `step`; shared hash-extract helpers + tests prove plaintext never written; dbt project can build marts from hashed sources; Cassandra suppress-only path is scaffolded; no live vendor credentials required for green tests.

---

## Product Contract

### Summary

Operators need DROP requests matched and suppressed across Habeas’s other systems the same way the data vertical uses precomputed hashes. Each external system gets its own worker and attempt table. Identifier hashing for index builds happens in the extract worker so Habeas never stores unhashed PII from those systems. Matching joins DROP hashes to system-specific BQ marts; suppression uses opaque vendor ids from match results.

### Problem Frame

App scaffolds (`app/mailchimp`, `paylocity`, `lever`, `auth0`, `google_sheets`, `cassandra`) exist but have no attempt tables, routes, adapters, or hash pipelines. Landing vendor PII into BigQuery “like MDR” would create a second HR/marketing PII warehouse — unacceptable for Paylocity/Lever especially.

### Key Decisions

- KD1. (session-settled: user-directed) Hash in the extract worker in memory; persist only hashed + opaque vendor ids to BigQuery hashed-raw tables.
- KD2. (session-settled: user-directed) dbt owns versioning from hashed raw → durable builds → serving marts (mirror `transform/drop_hash` swap/patch pattern, scoped per system).
- KD3. (session-settled: user-directed) One worker + one attempt table per bounded context; `step` discriminates `matching` vs `suppression` (Cassandra: `suppression` only).
- KD4. (session-settled: user-directed) Wide hashed-raw rows per vendor record are fine within a system; dbt projects to marts. Not a blocking schema debate.
- KD5. (session-settled: user-directed) Live API credential onboarding / Slack asks are **out of this implementation plan** — stubs + Secret Manager path names only.
- KD6. Matching against external marts uses the same CPPA SHA-256 Base64 rules as `drop_normalize` / DROP v1.2.0.

### Requirements

- R1. Create Postgres attempt tables for mailchimp, paylocity, lever, auth0, google_sheets with `step IN ('matching','suppression')` following Schema-Mailchimp-Attempts + existing `matching_attempts` / `data_fulfillment_attempts` conventions (terminal guard, claim columns, status enum, unique `(request_id, step, attempt_number)`).
- R2. Create `cassandra_attempts` with `step IN ('suppression')` only (data-vertical suppress pipe).
- R3. Register all new request-grain attempt tables with the shared reaper.
- R4. Each match/suppress app exposes `/matching/submit`, `/matching/collect`, `/suppression/submit`, `/suppression/collect` (Cassandra: suppression routes only) claiming by `step`.
- R5. Shared library helpers standardize + hash identifiers (email/phone/ndz fields) using DROP-compatible logic; unit tests prove helpers and that extract writers accept only hashed payloads (no plaintext column writers).
- R6. BigQuery hashed-raw + dbt project under `transform/` for external systems: sources = hashed tables; marts suitable for hash lookup by system; manual refresh path documented (no plaintext models).
- R7. Hash-index refresh control plane: queue attempts (system-scoped) so ops can manually refresh a system’s hashed extract + dbt build without coupling to DROP state refresh.
- R8. Vendor vocabulary (`mc_user_id`, `paylocity_employee_id`, etc.) stays inside each app’s `adapters/`.
- R9. No PII in logs, `error_message`, or `audit_payload` / attempt JSONB — redact; never store raw email/phone/name/DOB/ZIP in Postgres or BQ from these extractors.
- R10. Paylocity suppression remains approval-gated via existing `suppress.paylocity` rule (worker checks gate / leaves pending until approved — follow approval workflow patterns; do not bypass).
- R11. Stub adapters return deterministic fixture behavior for tests; real HTTP clients are interfaces only until credentials land.

### Scope

**In scope:** migrations; core hash-extract + refresh helpers; `transform/external_hash/` dbt skeleton; FastAPI scaffolds for six apps; reaper registration; unit/migration tests; AGENTS/README updates for new paths.

**Out of scope:** live Mailchimp/Paylocity/Lever/Auth0/Sheets API calls; Secret Manager secret creation; Terraform Cloud Run deploy; Vertica / CEPI workers; admin UI journey wiring for Tier-C verticals; production dbt runs; credential Slack onboarding copy (follow-up conversation).

### Actors

- A1. Ops / agent — enqueue hash refresh; trigger worker crons later.
- A2. Matching/suppression workers — claim attempts, call adapters.
- A3. Data owner / HR (Paylocity) — approval gate before suppress.

### Key Flows

- F1. Hash refresh — claim `*_hash_refresh` attempt → extract (stub/live) → hash in memory → write BQ hashed raw → dbt build → mark success.
- F2. Matching — pending `step=matching` → lookup DROP hashes against system mart (stub ok) → write match columns / terminal status.
- F3. Suppression — pending `step=suppression` (after match + gates) → adapter suppress by opaque id → terminal status.

### Acceptance Examples

- AE1. Migration up creates six attempt tables with expected `step` checks and terminal guards.
- AE2. Hash helper: plaintext email in → Base64 SHA-256 out matching `drop_normalize` / CPPA email vector.
- AE3. Extract writer rejects or has no API for plaintext fields (type/schema test).
- AE4. Mailchimp worker matching submit claims only `step=matching` pending rows.
- AE5. Cassandra worker has no matching routes; suppression submit claims `step=suppression`.
- AE6. Reaper config list includes all new attempt tables.
- AE7. dbt project parses / documents build for at least one system model graph (compile or sqlfluff-free dry structure + README).

---

## Planning Contract

### Key Technical Decisions

| ID | Decision |
|----|----------|
| KTD1 | One migration file (or tightly sequenced pair) for all attempt tables + hash refresh tables to keep dbmate ordering simple; prefixes `mailchimp_`, `paylocity_`, `lever_`, `auth0_`, `google_sheets_`, `cassandra_`, `vertical_hash_`. |
| KTD2 | Hash refresh: single table `vertical_hash_refresh_attempts` with `system VARCHAR` CHECK allowlist + `vertical_hash_refresh_runs` append-only (mirrors `hash_index_refresh_*` but system-scoped, not state-scoped). |
| KTD3 | Shared extract/hash code in `habeas_privacy_core` under something like `vertical_hash/` — wrap or vendoring-call `drop_normalize` hashing/standardize; do **not** put vendor API clients in core. |
| KTD4 | dbt home: `transform/external_hash/` — per-system schemas/datasets naming `external_hash_<system>` or dataset `external_hash_index` with system-prefixed tables; serving marts `(hash_value, vendor_record_id, system, built_at)`. |
| KTD5 | Worker pattern: copy structure from `app/matching` / ADR-11 routes; claim via core queue helpers; stub adapters in `app/<sys>/adapters/`. |
| KTD6 | Postgres attempt JSONB columns: prefer allowlisted `audit_payload` over raw request/response PII blobs from Schema example — align with privacy invariants (no `raw_request_payload` with emails). |
| KTD7 | Cassandra: no hash refresh membership; suppress only. |
| KTD8 | Google Sheets: hashed extract still required; document that Sheets source remains plaintext at Google — Habeas side never lands plaintext. |

### Assumptions

- Workspace packages for the six apps already exist in `pyproject.toml` / uv.
- DROP list types for MVP external matching are primarily **email** (and phone/NDZ where the system has fields); Mailchimp email-first is enough for first mart models.
- Stub extractors synthesize hashed rows from fixtures without calling vendors.

### Open Questions

- OQ1. (deferred) Exact BQ dataset name in `example-gcp-project` for external hash index — default `external_hash_index`; confirm with Jose before prod apply.
- OQ2. (deferred) Whether matching workers query BQ directly or share a core lookup helper like `matching/adapters/drop_hash.py` — prefer thin per-system adapter calling shared lookup interface.
- OQ3. (deferred) Live field allowlists per HR API — settle during credential onboarding.

### Dependencies and sequencing

1. U1 (core hash helpers) before U4 (dbt) and worker extract stubs (U5–U10).
2. U2 (migrations) before U3 (reaper) and workers.
3. U5–U10 parallel after U1+U2.
4. U11 docs last.

### Product Contract preservation

Product Contract created in this `ce-plan-bootstrap` run from session + External-Integrations — no prior requirements-only sibling.

---

## Implementation Units

### U1. Core vertical hash helpers

- **Goal:** DROP-compatible standardize+hash + typed hashed-row model with no plaintext fields.
- **Files:** Create `libs/habeas-privacy-core/src/habeas_privacy_core/vertical_hash/` (`hashing.py`, `models.py`, `__init__.py`); Create `libs/habeas-privacy-core/tests/test_vertical_hash.py`; Modify package exports if needed.
- **Approach:** Reuse algorithms from `transform/drop_hash/drop_normalize` (email/phone/ndz) — import if packagable, or thin re-export/copy with shared tests against CPPA vectors. `HashedVendorRecord` pydantic model: `system`, `vendor_record_id`, optional `email_hash`/`phone_hash`/`ndz_hash`, `extracted_at`.
- **Patterns to follow:** `drop_normalize/hashing.py`, `habeas_privacy_core/audit/redaction.py`.
- **Test scenarios:**
  - Happy: known email → expected Base64 hash (CPPA vector).
  - Edge: empty/whitespace email → skipped or null hash, no crash.
  - Error: constructing/writing API does not accept `email=` plaintext field.
- **Verification:** `uv run --package habeas-privacy-core pytest libs/habeas-privacy-core/tests/test_vertical_hash.py -q`
- **Dependencies:** None

### U2. Attempt + hash-refresh migrations

- **Goal:** Land all per-system attempt tables + `vertical_hash_refresh_*`.
- **Files:** Create `db/migrations/20260730150001_vertical_external_attempt_tables.sql` (timestamp after latest); optional follow-up only if split required.
- **Approach:** Template from Schema-Mailchimp-Attempts + `matching_attempts` (privacy-safe: `audit_payload JSONB` allowlisted, not raw PII payloads). Systems: mailchimp, paylocity, lever, auth0, google_sheets (`matching`,`suppression`); cassandra (`suppression`). Refresh: `vertical_hash_refresh_attempts` (`system` check: five hash systems — no cassandra), `vertical_hash_refresh_runs` append-only. Terminal guards + REVOKE patterns.
- **Patterns to follow:** `db/migrations/20260714000005_matching_create_matching_attempts.sql`, `20260717000001_matching_hash_index_refresh.sql`, Schema-Mailchimp-Attempts.
- **Test scenarios:**
  - Happy: migration SQL contains expected table names and step checks (static test like `test_migrations.py`).
  - Edge: cassandra step check excludes matching.
- **Verification:** extend `libs/habeas-privacy-core/tests/test_migrations.py`; `uv run pytest …test_migrations.py -q`
- **Dependencies:** None (serialize vs other migrations)

### U3. Reaper registration

- **Goal:** Shared reaper knows the new request-grain tables.
- **Files:** Modify `app/reaper/src/reaper/` config / main where `ReapedTableConfig` list is built; Modify tests under `app/reaper/tests/` if present.
- **Approach:** Add configs for each `*_attempts` table (not hash refresh if `supports_attempt_retry=False` pattern for refresh — mirror hash_index_refresh).
- **Patterns to follow:** existing reaper registration for `matching_attempts` / `data_fulfillment_attempts`.
- **Test scenarios:** Happy: config list includes mailchimp_attempts … cassandra_attempts.
- **Verification:** reaper unit tests / import check.
- **Dependencies:** U2

### U4. dbt `transform/external_hash`

- **Goal:** Versioned hashed-raw → mart pipeline skeleton for external systems.
- **Files:** Create `transform/external_hash/` (`dbt_project.yml`, `models/`, `README.md`, `AGENTS.md`, sources.yml stubs); no plaintext models.
- **Approach:** Document datasets; stub staging models reading hashed sources; mart models `(hash_value, vendor_record_id, system, built_at)`; build+swap macro notes mirroring drop_hash (may be SQL comments + one example system e.g. mailchimp email).
- **Patterns to follow:** `transform/drop_hash/`.
- **Test scenarios:** AE7 — project layout + README runbook for manual refresh; optional `dbt parse` if profiles available, else structure + schema.yml tests declared.
- **Verification:** files exist; README documents hash-only invariant.
- **Dependencies:** U1 (conceptual); can parallel after plan

### U5. Mailchimp worker scaffold

- **Goal:** FastAPI app with matching/suppression submit/collect + stub adapters + error_policy.
- **Files:** Modify/Create under `app/mailchimp/src/mailchimp/` (`main.py`, `adapters/`, `error_policy.py`, routes); tests under `app/mailchimp/tests/`.
- **Approach:** ADR-11 route names; claim from `mailchimp_attempts` by step; stubs deterministic.
- **Patterns to follow:** ADR-11 snippet; thin matching worker patterns.
- **Test scenarios:** AE4; healthz; claim filter by step.
- **Verification:** `uv run --package mailchimp pytest app/mailchimp/tests -q` (or package test path).
- **Dependencies:** U1, U2

### U6. Paylocity worker scaffold

- **Goal:** Same as U5 for HR; respect `suppress.paylocity` approval gate in suppress submit (check pending approval / skip).
- **Files:** `app/paylocity/src/paylocity/**`, `app/paylocity/tests/**`
- **Dependencies:** U1, U2
- **Patterns:** U5 + approval workflow helpers.
- **Verification:** package pytest

### U7. Lever worker scaffold

- **Goal:** Match+suppress scaffold for Lever.
- **Files:** `app/lever/src/lever/**`, `app/lever/tests/**`
- **Dependencies:** U1, U2

### U8. Auth0 worker scaffold

- **Goal:** Match+suppress scaffold for Auth0.
- **Files:** `app/auth0/src/auth0/**`, `app/auth0/tests/**`
- **Dependencies:** U1, U2

### U9. Google Sheets worker scaffold

- **Goal:** Match+suppress scaffold; document DWD / sheet plaintext caveat in README.
- **Files:** `app/google_sheets/src/google_sheets/**`, `app/google_sheets/tests/**`
- **Dependencies:** U1, U2

### U10. Cassandra suppress worker scaffold

- **Goal:** Suppression-only routes; stub restricted_person_id insert adapter.
- **Files:** `app/cassandra/src/cassandra/**`, `app/cassandra/tests/**`
- **Dependencies:** U2
- **Test scenarios:** AE5

### U11. Vertical hash refresh worker hooks + core DB helpers

- **Goal:** Claim/process helpers for `vertical_hash_refresh_attempts` + optional thin endpoints (could live on each system worker as `POST /hash-refresh/process` or one shared pattern). Prefer **per-system** `POST /hash-refresh/process` on Mailchimp–Sheets workers calling shared core helper (Cassandra omitted).
- **Files:** Create `libs/.../db/vertical_hash_refresh.py`; Modify U5–U9 mains to add route; tests in core.
- **Approach:** Mirror `hash_index_refresh` claim/submit/complete; process body calls stub extract → hash models → (interface) BQ writer stub in tests.
- **Dependencies:** U1, U2, U5–U9 (route add can be part of each worker unit if cleaner — then U11 is core helpers only)

### U12. Docs / AGENTS alignment

- **Goal:** Root and app AGENTS/README state the hash-in-worker + dbt mart pattern; link External-Integrations.
- **Files:** Modify `app/*/AGENTS.md`, `transform/external_hash/AGENTS.md`, maybe `.agent/modules` only if needed (prefer not).
- **Dependencies:** U4–U10

---

## Verification Contract

```bash
uv sync --all-packages
uv run --group dev pytest libs/habeas-privacy-core/tests/test_vertical_hash.py libs/habeas-privacy-core/tests/test_migrations.py -q
uv run --group dev pytest app/mailchimp/tests app/paylocity/tests app/lever/tests app/auth0/tests app/google_sheets/tests app/cassandra/tests app/reaper/tests -q
# dbt: structure review; dbt parse if profiles present
```

Privacy: grep new attempt writers for email/phone plaintext keys; ensure redaction helpers used on error paths.

---

## Definition of Done

- [ ] All R1–R11 addressed or explicitly deferred with OQ
- [ ] AE1–AE7 evidenced by tests or documented verification
- [ ] Disjoint executor file ownership respected; reviewers + QCQA completed
- [ ] No secrets committed; no plaintext PII schemas in BQ models
- [ ] Plan body not edited for progress (git commits carry progress)

---

## Appendix

### Vertical inventory (KB)

| System | Vertical | Match | Suppress | Hash index |
|--------|----------|-------|----------|------------|
| Mailchimp | Marketing | yes | yes | yes |
| Paylocity | HR | yes | yes (approval) | yes |
| Lever | HR recruiting | yes | yes | yes |
| Auth0 | Tech | yes | yes | yes |
| Google Sheets | Ad-hoc | yes | yes | yes |
| Cassandra | Data pipe | no | yes | no |
| CEPI / Vertica / drop_hash | Data | existing | via Cassandra | existing `transform/drop_hash` |

### Session-settled pipeline

```
Vendor API → worker memory standardize+hash → BQ hashed raw → dbt build/swap marts
Request → *_attempts step=matching → mart lookup → step=suppression → vendor suppress
```
