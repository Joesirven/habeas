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
| [`vertical_hash/`](src/habeas_privacy_core/vertical_hash/) | External vertical hash helpers + allowlisted attempt audit |

Vendor adapters belong in `app/<name>/adapters/`, not here.

**Connections / gate:** Connecting credentials or completing Upload does not alone clear
matching — `evaluate_connection_gate` (Upload cadence / Live ~180-day rotation / wizard).
Soft login reminders: `evaluate_connection_reminder` (allowlisted codes only — no SMTP).
Assignment replaces invite redeem.
