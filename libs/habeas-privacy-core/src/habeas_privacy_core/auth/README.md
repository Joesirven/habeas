# auth/

Identity helpers and role resolution for admin-api: Identity-Aware Proxy headers
and verified Google ID token Bearer (application default credentials / Cloud Run).

## Identity helpers

| Helper | Role |
|--------|------|
| `parse_iap_email` | Strip `accounts.google.com:` prefix from IAP email header |
| `actor_from_iap_header` | Actor string from IAP header (`unknown` if missing) |
| `actor_from_bearer_id_token` | Verify `Authorization: Bearer` Google ID token; return email or `unknown` |
| `resolve_actor` | Verified Bearer + optional IAP header (see below); returns `ResolvedActor` |
| `is_authenticated_actor` | True when actor is not the unknown placeholder |

`ResolvedActor` includes `email` and `source` (`iap_header` \| `bearer_jwt` \| `None`).

Bearer verification uses `google.oauth2.id_token.verify_oauth2_token`. Audience
defaults to `ADMIN_API_ID_TOKEN_AUDIENCE` or the request URL origin (Cloud Run
service origin). Invalid tokens and `email_verified=false` fail closed (`unknown`).

`resolve_actor` when Bearer verifies: matching IAP email header → `iap_header`;
service-account Bearer + distinct user header → `iap_header`; disagreeing user
Bearer vs header → trust Bearer (`bearer_jwt`, ignore spoof); Bearer alone →
`bearer_jwt`. Header alone → `iap_header`.

Prefer `resolve_actor` / `ResolvedActor.email` in new code; keep
`actor_from_iap_header` for backward compatibility.

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

### Identity sources in admin-api

| Source | Role resolution |
|--------|-----------------|
| `iap_header` | Full allowlists (`super_admin` / `admin` / `legal` / `data_owner`) |
| `bearer_jwt` | Must be on `ADMIN_API_SUPER_ADMINS` only; otherwise `403` |

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
