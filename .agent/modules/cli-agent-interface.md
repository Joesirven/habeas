# module: cli-agent-interface

> Gate: agents running Habeas CLI or editing `clients/cli/habeas-cli/`.

## Hybrid model (locked)

| Operation | Path |
|-----------|------|
| Mutations (approve, reject, retry, rule changes, DROP process/enqueue) | HTTP → **admin-api** via ADC or IAP bearer |
| Analysis reads (SELECT, joins, state inspection) | Postgres **read-only role** via Cloud SQL Auth Proxy |
| Forbidden | insert, update, delete, truncate, data definition language; direct user→worker Cloud Run calls; `DATABASE_URL` as a mutation path |

## Auth to deployed admin-api (CLI path current; browser GIS intended / not prod 00023)

admin-api is the **resource server**. Cloud Run Identity-Aware Proxy (IAP) is
**off** (`--no-iap`). App-level `REQUIRE_IAP_IDENTITY=true` requires a verified
Google ID token Bearer. Header-alone (`X-Goog-Authenticated-User-Email` without
a verified Bearer) is **401**. Legal sources: `user_jwt` (GIS — browser only),
`bearer_jwt` (ADC / Cloud Run `aud`), `iap_header` (verified Bearer **plus**
IAP email). `allUsers` invoker is **stripped** on `admin-api-prod` and
`admin-api-dev` (remaining: compute SA + `jsirven@`).

CLI Application Default Credentials (ADC) and IAP login are **unchanged**. Do
**not** invent a Google Identity Services command, a browser-token login, or an
audience flag. Browser Google Identity Services is a **third client** (user
Bearer, `aud` = `IAP_OAUTH_CLIENT_ID`) — not a CLI path, and **not live on
prod web** (100% is `admin-web-prod-00023-fnz` nginx `/api`; 00024 at 0%).

| Who | How |
|-----|-----|
| **super_admin** | `habeas-cli auth login --adc` (or `ADMIN_API_AUTH=adc`) — ADC Cloud Run ID token only; email from JWT; must be on `ADMIN_API_SUPER_ADMINS` |
| **admin / data_owner** | `habeas-cli auth login` — same Cloud Run audience token via ADC **plus** `X-Goog-Authenticated-User-Email` bound to active `gcloud` account (`@habeas.us`); full allowlists |

Both CLI paths mint `aud` = `ADMIN_API_URL` origin (Cloud Run service URL, no
path). Deployed admin-api verifies that token against
`ADMIN_API_ID_TOKEN_AUDIENCE` (same origin). The API must pin **both**
`ADMIN_API_ID_TOKEN_AUDIENCE` and `IAP_OAUTH_CLIENT_ID` — OAuth-client-only pin
drops the Cloud Run audience and ADC CLI gets **401**.

```bash
export ADMIN_API_URL=https://admin-api-dev-hsa55rg7ja-uk.a.run.app
gcloud auth application-default login

# Super_admin (Bearer only)
uv run --package habeas-cli habeas-cli auth login --adc
uv run --package habeas-cli habeas-cli auth status

# Admin / data_owner (Bearer + email header bound to gcloud account)
uv run --package habeas-cli habeas-cli auth login
uv run --package habeas-cli habeas-cli drop hash-index-refresh process --execute
```

Credentials live in `~/.config/habeas-cli/credentials.json` (mode `0600`).
`auth logout` clears them. `ADMIN_API_AUTH` is `auto` (default: prefer stored
login), `adc`, or `iap`.

Do **not** re-run `infra/cloudbuild/admin-api-dev-iam.yaml` for this workflow —
it re-enables Cloud Run IAP and strips user invoker.

Optional simulate (super_admin only): `ADMIN_API_SIMULATE_ROLE=admin|data_owner|super_admin`.

Localhost admin-api needs no token.

## Agent rules

- Use `habeas-cli` subcommands — never raw `psql`; prefer CLI over ad-hoc curl.
- Default output: `--json` for machine parsing.
- `--execute` required for mutation subcommands; without it, dry-run only.
- Send header `X-Client: habeas-cli` on admin-api calls (audit surface tagging).
- Worker process/enqueue always via admin-api — never grant yourself worker `run.invoker`.
- Hash-index enqueue: pass `--state XX` or `--all-states` — no implicit CA default.

## Distribution

- Dev: `uv run --package habeas-cli habeas-cli …`
- Agents on servers: Docker image (Auth Proxy sidecar for read-only database role only)

## Future

Model Context Protocol server wraps this CLI — not a parallel implementation.
