# module: cli-agent-interface

> Gate: agents running Habeas CLI or editing `clients/cli/habeas-cli/`.

## Hybrid model (locked)

| Operation | Path |
|-----------|------|
| Mutations (approve, reject, retry, rule changes, DROP process/enqueue) | HTTP → **admin-api** via Identity-Aware Proxy bearer token |
| Analysis reads (SELECT, joins, state inspection) | Postgres **read-only role** via Cloud SQL Auth Proxy |
| Forbidden | insert, update, delete, truncate, data definition language; direct user→worker Cloud Run calls |

## Identity-Aware Proxy (required for remote admin-api)

Deployed `admin-api-dev` has IAP on, `REQUIRE_IAP_IDENTITY=true`, invoker = IAP SA only.
Localhost admin-api needs no token.

```bash
export ADMIN_API_URL=https://admin-api-dev-hsa55rg7ja-uk.a.run.app
export IAP_OAUTH_CLIENT_ID=<iap-oauth-client-id>   # Console → IAP → admin-api-dev
# Optional prefetch if ADC cannot mint:
export IAP_ID_TOKEN="$(gcloud auth print-identity-token --audiences="$IAP_OAUTH_CLIENT_ID")"

uv run --package habeas-cli habeas-cli drop hash-index-refresh process --execute
curl -sS -H "Authorization: Bearer ${IAP_ID_TOKEN:-$(gcloud auth print-identity-token --audiences=$IAP_OAUTH_CLIENT_ID)}" \
  "$ADMIN_API_URL/auth/me"
```

There is no `--no-iap` escape. Missing token against `*.run.app` fails closed.

## Agent rules

- Use `habeas-cli` subcommands — never raw `psql`; prefer CLI over ad-hoc curl (curl only with IAP bearer as above).
- Default output: `--json` for machine parsing.
- `--execute` required for mutation subcommands; without it, dry-run only.
- Send header `X-Client: habeas-cli` on admin-api calls (audit surface tagging).
- Worker process/enqueue always via admin-api — never grant yourself worker `run.invoker`.

## Distribution

- Dev: `uv run --package habeas-cli habeas-cli …`
- Agents on servers: Docker image (Auth Proxy sidecar for read-only database role only)

## Future

Model Context Protocol server wraps this CLI — not a parallel implementation.
