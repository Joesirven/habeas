# drop_ingestor

CA DROP land/promote worker (no CPPA HTTP). Unzips staged ZIPs into `drop_raw_requests`, then promotes thin `requests`.

```bash
uv run --package drop-ingestor uvicorn drop_ingestor.main:app \
  --reload --app-dir app/drop_ingestor/src --port 8083
```

| Endpoint | Role |
|----------|------|
| `POST /ingest/land` | Unzip → parse CSVs → insert `drop_raw_requests`; mark land attempt success |
| `POST /ingest/promote` | Thin `requests` for pending raw rows; **no** matching enqueue |
| `GET /healthz` / `GET /readyz` | Liveness / readiness |

Env: `DATABASE_URL`, `WORKER_ID` (optional), `SERVICE_NAME=drop-ingestor`,
`DROP_PARSED_BUCKET` (default `example-gcp-project-drop-parsed-dev`).

Land accepts `gcs_uri` (`gs://` only) or in-memory `zip_base64` for tests. No local disk.
