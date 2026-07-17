# auth/

Identity-Aware Proxy identity helpers and role resolution for admin-api.

## IAP helpers

| Helper | Role |
|--------|------|
| `parse_iap_email` | Strip `accounts.google.com:` prefix from IAP email header |
| `actor_from_iap_header` | Actor string for audit / mutation attribution (`unknown` if missing) |
| `is_authenticated_actor` | True when actor is not the unknown placeholder |

## Role allowlists (v1)

Admin-api maps IAP email → `super_admin` \| `admin` \| `data_owner` via environment allowlists. Lists accept comma- or pipe-separated emails (case-insensitive).

| Variable | Role |
|----------|------|
| `ADMIN_API_SUPER_ADMINS` | `super_admin` |
| `ADMIN_API_ADMINS` | `admin` |
| `ADMIN_API_DATA_OWNERS` | `data_owner` |

Precedence when an email appears in multiple lists: `super_admin` → `admin` → `data_owner`.

### Local development default

When **all** allowlists are empty and `REQUIRE_IAP_IDENTITY` is `false` (the local default), callers without an IAP header receive role `super_admin`. This keeps Vite and CLI workflows working against localhost without configuring emails.

When allowlists are configured, only listed emails receive a role. Unknown emails are denied (`403`) if identity is present; with `REQUIRE_IAP_IDENTITY=true`, missing IAP headers return `401`.

### API surface

- `GET /me` → `{ "email": "...", "role": "super_admin" | "admin" | "data_owner" }`
- `admin_api.roles.require_roles(...)` — FastAPI dependency factory for route gating

Admin-api DROP mutations use `REQUIRE_IAP_IDENTITY` + `require_drop_mutation_actor` (see `admin_api.drop_pipeline`). Full IAP JWT assertion verification remains a follow-up when the OAuth client audience is provisioned.

Part of [`habeas-privacy-core`](../../../).

**Agent rules:** [`AGENTS.md`](AGENTS.md)
