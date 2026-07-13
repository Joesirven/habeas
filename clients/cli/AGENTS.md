> inherits: ../../AGENTS.md

# AGENTS.md — clients/cli/

Habeas Typer command-line package lives in `habeas-cli/`.

## Hybrid access (locked)

- **Writes** → admin-api only (Identity-Aware Proxy token)
- **Reads** → Postgres read-only role for agent analysis
- **`--execute`** on mutation commands

Full rules → [`.agent/modules/cli-agent-interface.md`](../../.agent/modules/cli-agent-interface.md).
