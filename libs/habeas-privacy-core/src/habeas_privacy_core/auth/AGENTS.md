> inherits: ../../AGENTS.md

# AGENTS.md — habeas-privacy-core/auth/

Identity-Aware Proxy header and Google ID token Bearer parsing for admin-api,
plus role allowlist helpers.

- Imported by apps and CLI — never import app code from here.
- No vendor-specific adapter logic in this module (Google token verify is OK).
- Prefer Starlette types here (core has no FastAPI dependency); apps wire `Depends(...)`.
- Prefer `resolve_actor` over `actor_from_iap_header` for new call sites.
- Never log tokens, emails, or other personally identifiable information.
- Do not hardcode OAuth client IDs; read `IAP_OAUTH_CLIENT_ID` / `ADMIN_API_ID_TOKEN_AUDIENCE`.

## Identity sources

`ResolvedActor.source` is `iap_header` | `bearer_jwt` | `user_jwt` | `None`.

| Source | Meaning | Role gate (admin-api) |
|--------|---------|------------------------|
| `user_jwt` | Verified **human** Google Identity Services / IAP OAuth-client audience token (`IAP_OAUTH_CLIENT_ID`) | Full allowlists (same as `iap_header`) |
| `bearer_jwt` | Cloud Run-audience token (CLI Application Default Credentials) or any verified **service-account** token | Service-account → `ADMIN_API_SUPER_ADMINS` only; human Cloud Run Bearer → full allowlists |
| `iap_header` | Header email only after a verified Bearer: matching **human** header, or service-account Bearer + distinct user header | Full allowlists |

Header alone is never an identity (`unknown` / `source=None`). Public invoke
(`allUsers` `run.invoker`) stays stripped on `admin-api-prod` and
`admin-api-dev`. Do not re-open until Jose-gated DEV GIS `/me` proof plus
an explicit cutover. Disagreeing user Bearer vs header: trust Bearer
(`user_jwt` or `bearer_jwt`); ignore spoof.
Service-account Bearer whose header repeats the service-account email stays
`bearer_jwt` (not a user identity).

Roles: `super_admin` / `admin` / `legal` / `data_owner` via `ADMIN_API_*` env allowlists.
