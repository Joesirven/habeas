# auth/

Identity helpers and role resolution for admin-api: Identity-Aware Proxy headers
and verified Google ID token Bearer (application default credentials / Cloud Run
/ Google Identity Services).

## Identity helpers

| Helper | Role |
|--------|------|
| `parse_iap_email` | Strip `accounts.google.com:` prefix from IAP email header |
| `actor_from_iap_header` | Actor string from IAP header (`unknown` if missing) |
| `actor_from_bearer_id_token` | Verify `Authorization: Bearer` Google ID token; return email or `unknown` |
| `resolve_actor` | Verified Bearer + optional IAP header (see below); returns `ResolvedActor` |
| `is_authenticated_actor` | True when actor is not the unknown placeholder |

`ResolvedActor` includes `email` and `source`
(`iap_header` \| `bearer_jwt` \| `user_jwt` \| `None`).

Bearer verification uses `google.oauth2.id_token.verify_oauth2_token`. Audiences:

- `ADMIN_API_ID_TOKEN_AUDIENCE` or the request URL origin (Cloud Run service origin)
- `IAP_OAUTH_CLIENT_ID` (browser Google user ID tokens)

When either env pin is set, Host/origin is not an extra audience. Invalid tokens
and `email_verified=false` fail closed (`unknown`). Do not log tokens or emails.

Prefer `resolve_actor` / `ResolvedActor.email` in new code; keep
`actor_from_iap_header` for backward compatibility.

## Identity sources (`user_jwt` vs `bearer_jwt` vs `iap_header`)

`IdentitySource` is how `resolve_actor` classified a verified principal — not a
transport header name. Architecture B uses all three.

| Source | What verified | Typical caller | Role gate in admin-api |
|--------|---------------|----------------|------------------------|
| `user_jwt` | Human Google ID token whose `aud` is the IAP / Google Identity Services OAuth client (`IAP_OAUTH_CLIENT_ID`, suffix `.apps.googleusercontent.com`) | Browser JSON to admin-api as resource server | Same full allowlists as `iap_header` (plus assignment fallback) |
| `bearer_jwt` | Google ID token whose `aud` is a Cloud Run origin (`ADMIN_API_ID_TOKEN_AUDIENCE`), or any verified service-account token | CLI `auth login --adc`; nginx `/api` service-account Bearer with no distinct user header | Service-account email must be on `ADMIN_API_SUPER_ADMINS` only (`403` otherwise). Human Cloud Run Bearer uses full allowlists |
| `iap_header` | `X-Goog-Authenticated-User-Email` only after a verified Bearer (matching human, or service-account + distinct user). Header alone is never an identity. | CLI `auth login` (Bearer + matching user header); nginx Server-Sent Events (service-account Bearer + distinct user header) | Full allowlists (`super_admin` / `admin` / `legal` / `data_owner`) plus assignment fallback |

`source` is `None` when there is no verified Bearer (`unknown`). Header alone is never an identity.

### How `resolve_actor` chooses the source

A verified Bearer is required before any source other than `None`:

| Condition | Source | Email used |
|-----------|--------|------------|
| Matching **human** IAP email header | `iap_header` | Header (same as Bearer) |
| Service-account Bearer whose header **repeats the service-account email** | `bearer_jwt` | Bearer (self-copied header is not a user identity) |
| Service-account Bearer + **distinct user** header | `iap_header` | Header (service-account impersonation / nginx rollback) |
| Disagreeing **user** Bearer vs header | `user_jwt` if OAuth-client audience, else `bearer_jwt` | Bearer (ignore spoofed header) |
| Cloud Run-audience Bearer alone | `bearer_jwt` | Bearer |
| OAuth-client-audience **user** Bearer alone | `user_jwt` | Bearer |
| OAuth-client-audience **service-account** Bearer alone | `bearer_jwt` | Bearer |
| No verified Bearer (header present or not) | `None` | `unknown` |

Header alone is never an identity. Without a verified Bearer (missing token, or
token that failed verify), `resolve_actor` returns `unknown` / `source=None`
(401 when identity is required). `X-Goog-Authenticated-User-Email` is never
trusted by itself. Public invoke (`allUsers` `run.invoker`) stays stripped on
`admin-api-prod` and `admin-api-dev`. Do not re-open until Jose-gated DEV GIS
`/me` proof plus an explicit cutover.

## Role allowlists (v1)

Admin-api maps authenticated email → `super_admin` \| `admin` \| `legal` \|
`data_owner` via environment allowlists. Lists accept comma- or pipe-separated
emails (case-insensitive).

| Variable | Role |
|----------|------|
| `ADMIN_API_SUPER_ADMINS` | `super_admin` |
| `ADMIN_API_ADMINS` | `admin` |
| `ADMIN_API_LEGALS` | `legal` |
| `ADMIN_API_DATA_OWNERS` | `data_owner` |

Precedence when an email appears in multiple lists: `super_admin` → `admin` →
`legal` → `data_owner`.

### Local development default

When **all** allowlists are empty and `REQUIRE_IAP_IDENTITY` is `false` (the
local default), callers without IAP/Bearer identity receive role `super_admin`
on the IAP-header path. This keeps localhost workflows working without
configuring emails.

When allowlists are configured, only listed emails receive a role. Unknown
emails are denied (`403`) if identity is present; with `REQUIRE_IAP_IDENTITY=true`,
missing identity returns `401`.

### API surface

- `GET /me` → `{ "email", "role", "real_role" }` (`role` may be simulated;
  `real_role` is the allowlist role)
- `admin_api.roles.require_roles(...)` — FastAPI dependency factory for route gating
- `X-Dev-Simulate-Role` — only when **real** role is `super_admin`

Admin-api DROP mutations use `REQUIRE_IAP_IDENTITY` + `require_drop_mutation_actor`
(see `admin_api.drop_pipeline`).

Part of [`habeas-privacy-core`](../../../).

**Agent rules:** [`AGENTS.md`](AGENTS.md)
