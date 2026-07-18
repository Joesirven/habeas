> inherits: ../../AGENTS.md

# AGENTS.md — habeas-cli

Typer package `habeas-cli`. UV workspace member.

- Mutations → admin-api (Identity-Aware Proxy via `IAP_OAUTH_CLIENT_ID` / `IAP_ID_TOKEN`); send `X-Client: habeas-cli`
- Reads → Postgres read-only role
- Entrypoint: `habeas-cli` console script
- DROP ops: `drop pipeline` (read); mutations require `--execute` (dry-run default):
  `drop download|land|promote|dispatch|match|fulfill`, `drop hash-index-refresh …`
  - `land` / `promote` / `dispatch` / `fulfill` accept optional admin-api body fields
    as CLI options (e.g. `--limit`, `--request-id`, `--gcs-uri`)

See [`.agent/modules/cli-agent-interface.md`](../../../.agent/modules/cli-agent-interface.md).
