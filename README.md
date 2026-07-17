# data-privacy

Implementation repository for **Habeas Data Privacy Request Automation** — consumer privacy request intake, matching, suppression, and audit on Google Cloud Platform.

| | |
|---|---|
| **Knowledge base** | `~/Documents/SirvenOS/Habeas/Projects/Data Privacy/` |
| **Agent onboarding** | [`AGENTS.md`](AGENTS.md) |
| **Remote** | `ssh://git@git.example.internal:7999/dsts/data-privacy.git` |

---

## Layout (v4)

```
data-privacy/
├── pyproject.toml              # UV workspace root
├── uv.lock
├── libs/habeas-privacy-core/ # shared Python library
├── transform/drop_hash/        # production dbt DROP hash-index marts
├── app/                        # Cloud Run FastAPI apps
│   ├── admin_api/              # control plane (Identity-Aware Proxy)
│   ├── drop_connector/         # DROP Type-I download / upload
│   ├── drop_ingestor/          # land (unzip) + promote to raw
│   ├── hash_index_refresh/     # per-state dbt refresh + rematch enqueue
│   ├── matching/               # hash + plaintext matching (all sources)
│   ├── mailchimp/ …            # per-system automation apps
│   └── reaper/ …
├── clients/
│   ├── web/                    # admin UI — Pipeline + Health Drop ops
│   └── cli/habeas-cli/       # Habeas Typer CLI
├── db/migrations/              # unified dbmate SQL
├── infra/
└── scripts/
```

---

## Stack (locked)

| Layer | Choice |
|-------|--------|
| Python | UV workspace, FastAPI, asyncpg, Pydantic models in core |
| Web | Vite, React, TypeScript, TanStack Router, TanStack Query, shadcn, Bun |
| Live updates | Server-Sent Events on admin-api; Postgres LISTEN/NOTIFY on approval tables |
| Database | Cloud SQL PostgreSQL 16, dbmate migrations |
| Deploy | Cloud Run (apps), Firebase Hosting (web), Cloud Build |

---

## Getting started

```bash
uv sync --all-packages
uv run --group dev pytest
uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir app/admin_api/src
uv run --package habeas-cli habeas-cli version
cd clients/web && bun install && bun run dev
export DATABASE_URL="postgres://…"             # Cloud SQL Auth Proxy
dbmate -d db/migrations up
```
