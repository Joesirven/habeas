> inherits: ../AGENTS.md

# AGENTS.md — app/google_sheets/

**Kind:** automation (catalog-system scaffold — **not** the matcher)

This directory is the catalog-system scaffold. It is **not** a queue consumer.
**Alumni** (`google_sheets_alumni`) and **Contact Us** (`google_sheets_contact_us`)
workers own `google_sheets_attempts` and hash-refresh claims. Those apps live on
the other checkout (`agent/connection-error-triage`). **Do not create those two
apps in this worktree.** Do not re-enable claiming here — that steals their work.

Library modules `hash_extract.py`, `vertical_match.py`, and `dbt_runner.py` stay
on disk for a later port into those two workers. Process routes must not import
them to claim or complete attempts.

- Process routes (`POST /matching/submit`, `/matching/collect`, `/suppression/submit`,
  `/suppression/collect`, `/hash-refresh/process`) **must not** claim
  `google_sheets_attempts` or the per-`system` hash-refresh queue. They return
  **503**. Do not re-enable `claim_next` / `claim_vertical_hash_refresh` here.
- Health stays: `GET /healthz`, `GET /readyz`. Ready still needs `DATABASE_URL`.
- **Do not invent cadence.** Owner OAuth and any freshness gate stay in
  freshness/gate (see
  [`docs/plans/2026-08-21-001-feat-sheets-owner-oauth-cadence-gate-plan.md`](../../docs/plans/2026-08-21-001-feat-sheets-owner-oauth-cadence-gate-plan.md)).
  Do not persist `refresh_policy` or stamp `last_successful_refresh_at` here.
- No personally identifiable information in logs. Attempt `audit_payload` is
  allowlisted (adapter, step, system, flags, error codes) — never hashes, emails,
  phones, names, or vendor ids.
- Vendor adapter code in `adapters/` inside this app only. No cross-import from
  other apps.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `google_sheets_`.
