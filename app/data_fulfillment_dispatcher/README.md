# data_fulfillment_dispatcher

Fulfillment stub for DROP requests: sets `drop_raw_requests.response_status`
only after `matching.review` is approved. No live suppression connectors.

```bash
uv run --package data-fulfillment-dispatcher uvicorn data_fulfillment_dispatcher.main:app \
  --reload --app-dir app/data_fulfillment_dispatcher/src --port 8085
```

| Endpoint | Role |
|----------|------|
| `POST /fulfill` | Map `match_count` → CPPA `response_status` (3 / 4 / 5) |
| `GET /healthz` / `GET /readyz` | Liveness / readiness |

**Body:** optional `{ "request_id": "<uuid>" }` or `{ "limit": 100 }` for batch.

**Status mapping** (same `matching.review` gate for all three):

| Latest `match_count` | `response_status` |
|----------------------|-------------------|
| 0 | `5` (Not found) |
| 1 | `3` (Deleted) |
| N > 1 | `4` (Opted out) |

Clear `matching.review` via admin Unit 8b bulk-approve-by-match-type when
operators approve multi-match (status-4 path) or other match types in bulk.

**Queue table:** none. No new reaper registry entry. Candidates are DROP
`requests` with approved `matching.review`, a `matching_results` row, and
`response_status IS NULL`.

Env: `DATABASE_URL`, `SERVICE_NAME=data-fulfillment-dispatcher`, optional
`FULFILL_BATCH_SIZE`.
