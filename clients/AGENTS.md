> inherits: ../AGENTS.md

# AGENTS.md — clients/

Operator-facing **control plane surfaces**. Admin web deploys as a static SPA on Cloud Run behind Identity-Aware Proxy (`admin-web-dev` / `admin-web-prod`); CLI is local UV.

| Path | Runtime | Role |
|------|---------|------|
| `web/` | Bun, Vite, React → nginx on Cloud Run | Browser admin UI → admin-api (IAP SSO front door) |
| `cli/habeas-cli/` | UV, Typer | Habeas CLI — mutations via admin-api; SELECT-only database reads |

Both use the same admin-api contract for writes. See [`.agent/modules/cli-agent-interface.md`](../.agent/modules/cli-agent-interface.md) and [`.agent/modules/frontend-stack.md`](../.agent/modules/frontend-stack.md).
