# drop_notice_dispatcher

Weekly DROP notice batch uploader (U10). Groups notice-approved DROP requests by
`source_csv_filename`, builds Id,Status CSVs, and POSTs to `drop_connector` `/upload`.
Does **not** call CPPA directly — sandbox guard lives in the connector.

```bash
uv run --package drop-notice-dispatcher uvicorn drop_notice_dispatcher.main:app \
  --reload --app-dir app/drop_notice_dispatcher/src --port 8086
```

| Endpoint | Role |
|----------|------|
| `POST /upload-weekly` | Find ready rows → batch upload via connector |
| `GET /healthz` / `GET /readyz` | Liveness / readiness |

**Body:** optional `{ "limit": 5000 }` for batch finder.

**Gates:** `intake_source=drop`, `response_status` set, `notice_review_status=approved`,
approved `approval_requests` with `action_type=notice.review`.

**Idempotency:** skips filenames already ledgered in `drop_response_submissions`
(`submission_type=upload`).

Env: `DATABASE_URL`, `DROP_CONNECTOR_URL` (default `http://127.0.0.1:8081`),
`SERVICE_NAME=drop-notice-dispatcher`, optional `UPLOAD_BATCH_LIMIT`.

## Cloud Scheduler (dev)

Friday end-of-day Pacific — HTTP `POST` to `/upload-weekly` on the Cloud Run service
(e.g. `drop-notice-dispatcher-dev`). Example (adjust URL after deploy):

```yaml
# infra/cloudbuild/drop-notice-dispatcher-dev.yaml deploys the service.
# Scheduler (manual / Terraform later):
#   schedule: "0 17 * * 5"   # 5pm PT Fridays (adjust for DST)
#   time_zone: America/Los_Angeles
#   http_target:
#     uri: https://drop-notice-dispatcher-dev-....run.app/upload-weekly
#     http_method: POST
#     oidc_token: { service_account_email: <scheduler-sa>@... }
```

Local chain: run `drop_connector` on 8081, then `POST http://127.0.0.1:8086/upload-weekly`.
