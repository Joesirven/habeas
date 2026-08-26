# Google Sheets (catalog-system scaffold)

This package is **not** the matcher. Catalog `system` is still
**`google_sheets`**. Live claimers are the **Alumni**
(`google_sheets_alumni`) and **Contact Us** (`google_sheets_contact_us`)
workers — they own `google_sheets_attempts` and hash-refresh claims.

Those workers live on the other checkout (`agent/connection-error-triage`).
**Do not create those two apps in this worktree.**

This directory keeps health plus the same route names as other vertical stubs
so the catalog language stays `SYSTEM = google_sheets`. Process routes return
**503** and do **not** claim. Do not re-enable claiming here. Process work
from Alumni or Contact Us on the other checkout.

Library modules `hash_extract.py`, `vertical_match.py`, and `dbt_runner.py`
remain on disk for a later port into those two workers. They are not wired
to process routes here.

Cloud Run FastAPI scaffold — health + refuse-claim step routes. Depends on
[`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)

**Do not invent cadence here.** Owner OAuth and any freshness gate stay in
freshness/gate:
[`docs/plans/2026-08-21-001-feat-sheets-owner-oauth-cadence-gate-plan.md`](../../docs/plans/2026-08-21-001-feat-sheets-owner-oauth-cadence-gate-plan.md).
This package does not persist `refresh_policy`, stamp `last_successful_refresh_at`,
or evaluate a freshness gate.
