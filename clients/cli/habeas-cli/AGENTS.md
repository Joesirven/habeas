> inherits: ../../AGENTS.md

# AGENTS.md — habeas-cli

Typer package `habeas-cli`. UV workspace member.

- Mutations → admin-api (Identity-Aware Proxy); send `X-Client: habeas-cli`
- Reads → Postgres read-only role
- Entrypoint: `habeas-cli` console script
- DROP Phase 1: `drop pipeline`, `drop hash-index-refresh …`, `drop match` (spine
  download/land/promote/dispatch/fulfill proxies deferred)

See [`.agent/modules/cli-agent-interface.md`](../../../.agent/modules/cli-agent-interface.md).
