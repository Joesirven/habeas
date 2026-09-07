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

Env: `DATABASE_URL`, `SERVICE_NAME=request-dispatcher`, optional `DISPATCH_BATCH_SIZE`,
optional `DISPATCH_VERTICAL_LIST_TYPES`.

### `DISPATCH_VERTICAL_LIST_TYPES`

Comma-separated DROP list types eligible for vertical enqueue on Auth0, Axios
HQ (`axios_headquarters`), `hr_alumni`, and `bizdev_contacts`. Allowed values:
`Email`, `Phone`, `NDZ`.

| Value | When |
|-------|------|
| *(unset / empty)* | Default **Email only** — avoids flooding ~1.2M Phone/NDZ attempts before marts are ready |
| `Email` | Same as default |
| `Email,Phone,NDZ` | After external_hash phone/ndz marts are verified (or Jose-approved empty) |

Cutover order (hashed_raw → hash-refresh → dbt marts → this env → drain):
[`transform/external_hash/README.md`](../../transform/external_hash/README.md) § Phone/NDZ cutover order.
