> inherits: ../../AGENTS.md

# AGENTS.md — habeas-privacy-core/auth/

Identity-Aware Proxy header parsing and DROP ops role allowlists for admin-api.

- Imported by apps and CLI — never import app code from here.
- No vendor-specific logic in this module.
- Roles: `super_admin` / `admin` / `data_owner` via `DROP_OPS_*_EMAILS` env allowlists.
- Prefer Starlette types here (core has no FastAPI dependency); apps wire `Depends(...)`.
