> inherits: ../AGENTS.md

# AGENTS.md — habeas-privacy-core

Shared library package. Each submodule under `src/habeas_privacy_core/` has its own AGENTS.md and README.md:

| Module | Purpose |
|--------|---------|
| [`models/`](src/habeas_privacy_core/models/) | Pydantic domain models — shared everywhere |
| [`db/`](src/habeas_privacy_core/db/) | asyncpg pool, requests table helpers |
| [`geo/`](src/habeas_privacy_core/geo/) | State acronym normalize + served-state allowlist (enqueue / rematch / BQ lookup) |
| [`queue/`](src/habeas_privacy_core/queue/) | Queue-as-table claim, heartbeat, reap |
| [`workflow/`](src/habeas_privacy_core/workflow/) | Approval and service level agreement helpers |
| [`audit/`](src/habeas_privacy_core/audit/) | Audit writer, middleware, redaction |
| [`adapters/`](src/habeas_privacy_core/adapters/) | Protocol bases and shared integration helpers |
| [`observability/`](src/habeas_privacy_core/observability/) | Logging, tracing, metrics |
| [`auth/`](src/habeas_privacy_core/auth/) | Identity-Aware Proxy identity parsing |
| [`live/`](src/habeas_privacy_core/live/) | NOTIFY helpers for live events |

Vendor adapters belong in `app/<name>/adapters/`, not here.
