> inherits: ../AGENTS.md

# AGENTS.md — habeas-privacy-core

Shared library package. Each submodule has its own AGENTS.md and README.md:

| Module | Purpose |
|--------|---------|
| [`models/`](models/) | Pydantic domain models — shared everywhere |
| [`db/`](db/) | asyncpg pool and transactions |
| [`queue/`](queue/) | Queue-as-table claim, heartbeat, reap |
| [`workflow/`](workflow/) | Approval and service level agreement helpers |
| [`audit/`](audit/) | Audit writer, middleware, redaction |
| [`adapters/`](adapters/) | Protocol bases and shared integration helpers |
| [`observability/`](observability/) | Logging, tracing, metrics |
| [`auth/`](auth/) | Identity-Aware Proxy identity parsing |
| [`live/`](live/) | NOTIFY helpers for live events |

Vendor adapters belong in `app/<name>/adapters/`, not here.
