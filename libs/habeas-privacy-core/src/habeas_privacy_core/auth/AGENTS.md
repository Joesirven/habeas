> inherits: ../../AGENTS.md

# AGENTS.md — habeas-privacy-core/auth/

Identity-Aware Proxy header and Google ID token Bearer parsing for admin-api,
plus role allowlist helpers.

- Imported by apps and CLI — never import app code from here.
- No vendor-specific adapter logic in this module (Google token verify is OK).
- Roles: `super_admin` / `admin` / `data_owner` via `ADMIN_API_*` env allowlists.
- Prefer Starlette types here (core has no FastAPI dependency); apps wire `Depends(...)`.
- Prefer `resolve_actor` over `actor_from_iap_header` for new call sites.
