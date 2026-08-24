---
title: "Google Sheets owner OAuth + refresh cadence gate"
date: 2026-08-21
type: feat
topic: sheets-owner-oauth-cadence-gate
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: session-2026-08-21
execution: code
---

## Goal Capsule

Ship Google Sheets connections on the **owner OAuth** path proven in the `/dev/sheets-oauth` lab (no share-to-GCP-SA), with an explicit wizard **data-refresh cadence** step. **Volatile** sheets hard-gate matching when a new intake batch arrives **and** the connection’s last successful extract→hash→mart cycle is older than **12 hours**. **Static** sheets require one successful cycle after connect. Login is never blocked — soft reminders only.

**Base:** build on `agent/vertical-scoped-connectors` (owner wizard, `freshness.py` / `matching_gate.py` already exist). Port lab OAuth redeem/test into production connections (Secret Manager, not process memory).

## Settled decisions (2026-08-21)

| ID | Decision |
|----|----------|
| KD1 | Sheets auth = owner Google OAuth offline refresh token in Secret Manager (`dpra/connections/google_sheets/{connection_id}`). Retire SA-share as the owner path. |
| KD2 | Wizard asks cadence: **Static** (rarely/never changes) vs **Volatile** (can change; matching may block until refresh). |
| KD3 | Volatile freshness trigger = **new intake batch**, with **minimum refresh interval 12 hours** per connection: if last successful refresh is &lt; 12h ago, additional same-day batches do **not** re-stale the connection. |
| KD4 | Matching hard-gated when overdue; login soft-remind only (`evaluate_connection_reminder`). |
| KD5 | Refresh success = extract + normalize/hash + mart rebuild completed for that connection/system (reuse vertical hash refresh run success timestamp). |

## Requirements

- R1. Sheets connect wizard: OAuth Connect → spreadsheet URL + test → cadence (Static | Volatile) → Confirm.
- R2. Persist `refresh_policy` (`static` \| `volatile`) and `min_refresh_interval_hours` (fixed **12** for volatile; not owner-editable below 12).
- R3. On intake batch promote (or equivalent “new batch ready for matching”), mark volatile connections **stale** only if `now - last_successful_refresh_at >= 12h`.
- R4. `evaluate_connection_gate` returns not-allowed with allowlisted code (e.g. `sheets_refresh_stale`) when volatile + stale; matching workers respect gate.
- R5. Soft login reminder when volatile overdue or approaching (optional approach window).
- R6. Static: after first successful refresh cycle, gate stays OK until reconnect/wizard reset/ops force-refresh.
- R7. No sheet cell PII in logs/toasts; test = `spreadsheets.get` metadata only.
- R8. Lab route may remain as `/dev/sheets-oauth` but production path is owner connectors + admin-api connections.

## Scope boundaries

- Out: DWD / robot `@habeas.us` share path; per-connection SA share onboarding.
- Out: Changing DROP weekly upload cadence (unrelated).
- Out: Auto-scraping sheets on a timer without owner action (owner-triggered refresh still required for volatile).

## Implementation units

### U1. Freshness model + gate rules

- **Files:** `libs/habeas-privacy-core/src/habeas_privacy_core/connections/freshness.py`, `matching_gate.py`, tests under `libs/habeas-privacy-core/tests/`
- **Approach:** Extend metadata keys: `refresh_policy`, `last_successful_refresh_at`, `last_intake_batch_id` / `stale_since_batch_at`. Gate: volatile + (`now - last_successful_refresh_at >= 12h` after a newer intake signal) → block. Static → only wizard_incomplete / missing first refresh.
- **Tests:** 12h floor with two batches same day; batch after 12h+; static never stale on batch; wizard incomplete.

### U2. Sheets OAuth production endpoints

- **Files:** `app/admin_api/src/admin_api/` (promote/adapt `lab_sheets_oauth.py` → owner/ops connections routes), Secret Manager writer, tests
- **Approach:** Start/redeem/test with PKCE; store JSON secret `{auth_mode, refresh_token, spreadsheet_url, …}`; connection test uses refresh token (lab pattern). Env: product OAuth client id/secret (not lab-only names long-term).
- **Tests:** redeem stores secret shape; test ok/auth_failed; non-`habeas.us` rejected.

### U3. Owner wizard UI — Sheets + cadence step

- **Files:** `clients/web/src/routes/owner/connectors.tsx` (and related), `clients/web/src/lib/api.ts`
- **Approach:** Replace SA-share copy with OAuth connect; cadence step: Static vs Volatile with plain-language “matching will wait until you refresh (at most every 12 hours)” for Volatile.
- **Tests:** component/API contract tests as existing wizard patterns allow.

### U4. Intake → stale signal

- **Files:** drop promote / matching enqueue path (`app/admin_api` or dispatcher) that already knows batch id
- **Approach:** After new intake batch is eligible for matching, for each assigned volatile `google_sheets` (and later other hash verticals if desired) connection: if last refresh ≥ 12h ago (or never), set stale / clear “fresh for this batch”. Idempotent.
- **Tests:** two promotes &lt; 12h apart → one refresh required; promote after 12h → stale again.

### U5. Owner refresh action → hash → mart

- **Files:** google_sheets worker hash-refresh route; enqueue vertical_hash_refresh; dbt/mart trigger as existing external_hash pattern
- **Approach:** “Refresh data” runs extract (hashed in memory) → BQ raw → mart rebuild; on success stamp `last_successful_refresh_at`.
- **Tests:** success clears gate; failure leaves stale.

## Verification

- Lab parity: OAuth as `jsirven@` against a real sheet still passes metadata test via production secret path.
- Volatile: batch1 → must refresh; batch2 within 12h → matching allowed without new refresh; after 12h + new batch → must refresh again.
- Static: one refresh; later batches do not block.
- Login with overdue volatile: reminder present; `/me` still 200.

## Risks

- OAuth client must be Workspace-internal; refresh_token omitted if consent reused — keep `prompt=consent` + document revoke.
- Defining “intake batch” precisely (DROP promote vs any matching wave) — prefer DROP land/promote batch id already used by pipeline.
- Building on wrong branch — use vertical-scoped-connectors worktree / merge base.

## Handoff

Implement from this plan on the vertical-scoped-connectors line of work; keep `/dev/sheets-oauth` until production wizard is green.
