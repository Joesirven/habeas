> inherits: ../AGENTS.md

# AGENTS.md — clients/

Operator-facing **control plane surfaces** — not Cloud Run fleet members (except web is static hosting).

| Path | Runtime | Role |
|------|---------|------|
| `web/` | Bun, Vite, React | Browser admin UI → admin-api |
| `cli/habeas-cli/` | UV, Typer | Habeas CLI — mutations via admin-api; SELECT-only database reads |

Both use the same admin-api contract for writes. See [`.agent/modules/cli-agent-interface.md`](../.agent/modules/cli-agent-interface.md) and [`.agent/modules/frontend-stack.md`](../.agent/modules/frontend-stack.md).
