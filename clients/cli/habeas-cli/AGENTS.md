> inherits: ../../AGENTS.md

# AGENTS.md — habeas-cli

Typer package `habeas-cli`. UV workspace member.

- Mutations → admin-api; send `X-Client: habeas-cli`
- Auth (deployed admin-api-dev): `habeas-cli auth login --adc` (super_admin, Bearer Google ID token) or `auth login` (admin / data_owner — Bearer + `X-Goog-Authenticated-User-Email`). See [`.agent/modules/cli-agent-interface.md`](../../../.agent/modules/cli-agent-interface.md).
- Reads → Postgres read-only role
- Entrypoint: `habeas-cli` console script
- DROP ops: `drop pipeline` (read); mutations require `--execute` (dry-run default):
  `drop download|land|promote|dispatch|match|fulfill`, `drop hash-index-refresh …`
  - `land` / `promote` / `dispatch` / `fulfill` accept optional admin-api body fields
    as CLI options (e.g. `--limit`, `--request-id`, `--gcs-uri`)
