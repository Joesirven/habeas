# request_dispatcher

Enqueues matching for thin `requests` that do not yet have `matching_attempts` rows.

```bash
uv run --package request-dispatcher uvicorn request_dispatcher.main:app \
  --reload --app-dir app/request_dispatcher/src --port 8084
```

| Endpoint | Role |
|----------|------|
| `POST /dispatch` | Enqueue matching for requests lacking attempts |
| `GET /healthz` / `GET /readyz` | Liveness / readiness |

Env: `DATABASE_URL`, `SERVICE_NAME=request-dispatcher`, optional `DISPATCH_BATCH_SIZE`.
