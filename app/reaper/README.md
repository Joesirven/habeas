# Reaper

Shared worker — releases expired leases, marks timeouts, inserts retry rows across all queue tables.

Cloud Run FastAPI service with `/healthz`, `/readyz`, structured JSON logging, and Postgres pool via `habeas-privacy-core`.

```bash
uv run --package reaper uvicorn reaper.main:app --reload --app-dir app/reaper/src
```

**Deploy:** [`infra/cloudbuild/reaper.yaml`](../../infra/cloudbuild/reaper.yaml)

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
