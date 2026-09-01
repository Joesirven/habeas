---
title: "Super-admin Connections — secure owner credential onboarding"
date: 2026-07-30
type: feat
topic: connections-onboarding
artifact_contract: ce-unified-plan/v1
artifact_readiness: shipped
product_contract_source: ce-plan-bootstrap
execution: code
status_note: >
  Shipped on master (dev) 2026-08: live per-system testers, owner wizard
  Confirm→Privacy→Credentials→Test, absolute invite URLs, ops retest + action
  toasts, invite not burned on failed test. Connecting ≠ enabling vertical matching.
  KB: SirvenOS External-Integrations § Connections onboarding.
---

> **SUPERSEDED (Mailchimp):** Communications is Axios HQ (`axios_hq` / `axios_headquarters`); do not treat Mailchimp as a live connection system — historical plan text left intact.

## Goal Capsule

Ship a **super_admin Connections** surface under Ops so Habeas can create per-system integration connections, send a **safe owner invite** (copyable signed URL; optional mailto), and let the owner submit dedicated credentials into **Secret Manager** with a **connection test** — without Slack DMs of secrets.

**Systems:** mailchimp, paylocity, lever, auth0, google_sheets (SaaS invite flows). **cassandra** = infra card only (no owner invite; INF handoff copy).

**Authority:** External-Integrations + session research 2026-07-30 (owner link UX) > ADR-11 workers > privacy invariants > this plan.

**Stop when:** super_admin can list/create connections, mint invite, owner redeem page accepts secrets (dev: memory/stub secret store), connection test returns pass/fail without echoing secrets; Cassandra is non-invite; tests green.

---

## Product Contract

### Summary

Super admins manage **Connections** at `/ops/connections`. Creating a connection for a SaaS system produces an invite for a named owner email. The owner opens a short-lived link, sees trust copy, pastes/grants credentials appropriate to that system, Habeas stores secrets out of Postgres, runs a system-specific connection test, and marks the connection connected or failed.

### Key Decisions

- KD1. (session-settled: user-directed) Live under **super_admin Ops** as Connections submenu (`/ops/connections`).
- KD2. (session-settled: research) Prefer dedicated integration secrets / grants; never ask for personal login passwords.
- KD3. (session-settled: research) Cassandra is **infra** — no invite form; document INF path.
- KD4. MVP invite delivery = **copy invite URL** (+ optional `mailto:`) — no SMTP required to ship.
- KD5. Secrets never returned after write; audit logs ids/status only.
- KD6. Connection test is server-side only; stubs acceptable when vendor unreachable (test harness mode).

### Requirements

- R1. Tables: `integration_connections`, `connection_invites` (token hash, TTL, single-use).
- R2. Super_admin APIs: list/create connections; create invite; revoke invite; trigger test; view status (no secret values).
- R3. Owner redeem API: validate token → accept system-specific credential payload → write secret via injectable SecretWriter → run test → burn token.
- R4. Web: Connections list + create/invite dialog; public-ish connect route `/connect/:token` (still behind same SPA; token is the auth).
- R5. Per-system field schemas + trust copy + stub connection testers.
- R6. Role gate: mutations require `super_admin`; redeem is token-gated (no role).
- R7. Google Sheets path collects spreadsheet URL + documents SA share (no JSON key paste).
- R8. Paylocity/Lever note Super Admin / IT may need to create app before paste.

### Scope

**In:** migration, core helpers, admin_api routes, web UI, stub secret store + stub testers, tests.

**Out:** Real SMTP, live Mailchimp/Paylocity OAuth apps, live GSM in CI, Cassandra credential form, full OAuth redirect flows (document as Phase 2).

### Acceptance Examples

- AE1. Super_admin creates mailchimp connection → invite URL returned once.
- AE2. Redeem with valid token + fake key → status connected (stub test pass); token reuse fails.
- AE3. Expired/invalid token → 400/404.
- AE4. Non–super_admin cannot create connection (403).
- AE5. Cassandra create is infra-only (no invite endpoint success / UI disables invite).
- AE6. UI lists connections with status chips; secrets never shown.

---

## Planning Contract

### Key Technical Decisions

| ID | Decision |
|----|----------|
| KTD1 | Place UI at `/ops/connections`; link from Health Configuration + Workers Settings. |
| KTD2 | SecretWriter protocol: `put_secret(secret_id, value)`; prod GSM later; MVP `InMemorySecretWriter` / env flag. |
| KTD3 | Invite token: `secrets.token_urlsafe(32)`; store SHA-256 hash only; TTL default 72h. |
| KTD4 | `secret_resource_name` on connection = `dpra/connections/{system}/{connection_id}` |
| KTD5 | Testers in `admin_api/connections/testers.py` (stubs return ok); interface ready for live HTTP. |
| KTD6 | System enum: mailchimp, paylocity, lever, auth0, google_sheets, cassandra |

### Implementation Units (10)

### U1. Migration
- Files: `db/migrations/20260730170001_core_integration_connections.sql`
- Tables `integration_connections`, `connection_invites`; tests in `test_migrations.py`

### U2. Core connections helpers
- Files: `libs/.../db/connections.py`, `libs/.../connections/` (models, token hash, secret writer protocol), tests

### U3. admin_api connections router (super_admin)
- Files: `app/admin_api/src/admin_api/connections.py`, wire in `main.py`, tests

### U4. Redeem + test endpoints
- Files: extend `connections.py` or `connections_redeem.py`; tests for token burn + test stub

### U5. Per-system credential schemas + trust copy
- Files: `libs/.../connections/systems.py` (field defs, trust markdown strings)

### U6. Stub connection testers
- Files: `app/admin_api/src/admin_api/connection_testers.py` + tests

### U7. Web API client
- Files: `clients/web/src/lib/api.ts` (types + functions only for connections)

### U8. Connections list page + router/nav
- Files: `clients/web/src/routes/ops/connections.tsx`, `router.tsx`, ops nav / AppShell links

### U9. Create connection + invite dialog
- Files: components under `clients/web/src/components/ops/Connection*.tsx` used by list page

### U10. Owner connect page `/connect/$token`
- Files: `clients/web/src/routes/connect.$token.tsx`, trust UI, form by system

---

## Verification Contract

```bash
uv run --group dev pytest libs/habeas-privacy-core/tests/test_connections*.py app/admin_api/tests/test_connections*.py -q
cd clients/web && bun test # or vitest if present for new files
```

## Definition of Done

- AE1–AE6 evidenced
- No secrets in git/logs/UI after submit
- Reviewers + 5 QCQA personas completed

## Ship notes (2026-08-03)

- Live testers replace stubs for Mailchimp / Paylocity / Lever / Auth0 / Sheets.
- Owner UI: four-step wizard; failed redeem keeps invite; allowlisted `detail` codes only.
- Ops: Connections detail supports invite mint/revoke and **Test connection** with confirm + toasts.
- Absolute invite URLs when sharing; `/connect/*` skips post-auth splash.
- **Out of band:** owner Slack/Jira outreach copy is session-only — do not store outreach templates in KB.
