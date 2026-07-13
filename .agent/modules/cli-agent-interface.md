# module: cli-agent-interface

> Gate: agents running Habeas CLI or editing `clients/cli/habeas-cli/`.

## Hybrid model (locked)

| Operation | Path |
|-----------|------|
| Mutations (approve, reject, retry, rule changes) | HTTP → **admin-api** via Identity-Aware Proxy bearer token |
| Analysis reads (SELECT, joins, state inspection) | Postgres **read-only role** via Cloud SQL Auth Proxy |
| Forbidden | insert, update, delete, truncate, data definition language |

## Agent rules

- Use `habeas-cli` subcommands — never raw `psql` or curl without the CLI wrapper.
- Default output: `--json` for machine parsing.
- `--execute` required for mutation subcommands; without it, dry-run only.
- Send header `X-Client: habeas-cli` on admin-api calls (audit surface tagging).

## Distribution

- Dev: `uv run --package habeas-cli habeas-cli …`
- Agents on servers: Docker image (Auth Proxy sidecar for read-only database role only)

## Future

Model Context Protocol server wraps this CLI — not a parallel implementation.
