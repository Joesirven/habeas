> inherits: ../AGENTS.md

# AGENTS.md — habeas-privacy-core

Shared library package. Each submodule under `src/habeas_privacy_core/` has its own AGENTS.md and README.md:

| Module | Purpose |
|--------|---------|
| [`models/`](src/habeas_privacy_core/models/) | Pydantic domain models — shared everywhere |
| [`db/`](src/habeas_privacy_core/db/) | asyncpg pool, requests table helpers |
| [`geo/`](src/habeas_privacy_core/geo/) | State acronym normalize + served-state allowlist (enqueue / rematch / BQ lookup) |
| [`queue/`](src/habeas_privacy_core/queue/) | Queue-as-table claim, heartbeat, reap |
| [`fleet/`](src/habeas_privacy_core/fleet/) | Worker fleet discovery conventions (Scheduler ∪ Cloud Run; no GCP clients) |
| [`workflow/`](src/habeas_privacy_core/workflow/) | Approval and service level agreement helpers |
| [`audit/`](src/habeas_privacy_core/audit/) | Audit writer, middleware, redaction |
| [`adapters/`](src/habeas_privacy_core/adapters/) | Protocol bases and shared integration helpers |
| [`observability/`](src/habeas_privacy_core/observability/) | Logging, tracing, metrics |
| [`auth/`](src/habeas_privacy_core/auth/) | IAP header + Bearer Google ID token identity parsing |
| [`live/`](src/habeas_privacy_core/live/) | NOTIFY helpers for live events |
| [`connections/`](src/habeas_privacy_core/connections/) | Vertical catalog, connection models, Secret Manager paths (no secret values logged); freshness/matching gate (`freshness.py`, `matching_gate.py`) |
| [`vertical_hash/`](src/habeas_privacy_core/vertical_hash/) | External vertical hash helpers — `drop_list_hash`, nullable hashed_raw (`email`/`phone`/`ndz`), multi-mart lookups + allowlisted attempt audit |
| [`sheet_worker/`](src/habeas_privacy_core/sheet_worker/) | Shared Sheets worker primitives (hash extract, list-type mart match/drain) for `hr_alumni` / `bizdev_contacts` |

Vendor adapters belong in `app/<name>/adapters/`, not here.

**External phone/NDZ:** `vertical_hash.drop_list_hash` routes DROP list types to
precomputed hash fields (never invent plaintext hashing). Hashed-raw rows keep
nullable `email_hash` / `phone_hash` / `ndz_hash` (≥1 required). Matching/
drain pick the per-kind serving mart. Marts and cutover order live in
[`transform/external_hash`](../../transform/external_hash/) — do not duplicate here.

**Connections / gate:** Connecting credentials or completing Upload does not alone clear
matching — `evaluate_connection_gate` (Upload cadence / Live ~180-day rotation / wizard).
Soft login reminders: `evaluate_connection_reminder` (allowlisted codes only — no SMTP).
Assignment replaces invite redeem.
