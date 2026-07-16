# drop_connector

CA DROP Type-I connector (sandbox): download ZIP, upload/amend `Id,Status` CSVs.

```bash
uv run --package drop-connector uvicorn drop_connector.main:app \
  --reload --app-dir app/drop_connector/src --port 8082
```

Env: `DROP_API_BASE_URL`, `DROP_API_KEY`, `DROP_ENV=sandbox` (URL must contain `/sandbox`).
