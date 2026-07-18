# auth/

Identity-Aware Proxy identity helpers and DROP ops role resolution for admin-api.

| Helper | Role |
|--------|------|
| `parse_iap_email` | Strip `accounts.google.com:` prefix from IAP email header |
| `actor_from_iap_header` | Actor string for audit / mutation attribution (`unknown` if missing) |
| `is_authenticated_actor` | True when actor is not the unknown placeholder |
| `parse_email_allowlist` | Pipe- or comma-separated emails → frozenset |
| `resolve_ops_role` | Email → `super_admin` / `admin` / `data_owner` (highest wins) |
| `resolve_me` / `bind_role_dependencies` | Fail-closed principal + FastAPI-ready role gates |

## DROP ops roles (env allowlists)

| Env | Role |
|-----|------|
| `DROP_OPS_SUPER_ADMIN_EMAILS` | `super_admin` |
| `DROP_OPS_ADMIN_EMAILS` | `admin` |
| `DROP_OPS_DATA_OWNER_EMAILS` | `data_owner` |
| `DROP_OPS_LOCAL_ROLE` | Local-only default when `REQUIRE_IAP_IDENTITY` is false (default `super_admin`) |

Emails may be pipe- or comma-separated. If an email appears on multiple lists, the highest privilege wins (`super_admin` > `admin` > `data_owner`).

When `REQUIRE_IAP_IDENTITY=true`, missing IAP → **401**; authenticated but not allowlisted → **403**.

**Web contract:** `GET /me` → `{ "email", "role" }` (U4). `GET /auth/me` remains the identity probe and also includes `role` when resolved.

Admin-api DROP mutations use these deps plus `REQUIRE_IAP_IDENTITY` (see `admin_api.drop_pipeline` and `infra/README.md`). Full IAP JWT assertion verification remains a follow-up when the OAuth client audience is provisioned.

Part of [`habeas-privacy-core`](../../../).

**Agent rules:** [`AGENTS.md`](AGENTS.md)
