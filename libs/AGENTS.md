> inherits: ../AGENTS.md

# AGENTS.md — libs/

Shared Python libraries. **Not deployed alone** — imported by `app/*` and `clients/cli/*`.

## Contents

| Package | Purpose |
|---------|---------|
| [`habeas-privacy-core/`](habeas-privacy-core/) | Models, queue, audit — each submodule has its own AGENTS.md and README.md |

## Rules

- All domain **Pydantic models** live here — one definition for every app and the CLI.
- No vendor-specific adapter implementations — those live in `app/<name>/adapters/`.
- Publish as internal wheel at version 1; MVP uses workspace-local dependency only.

If editing → read [`.agent/modules/python-uv.md`](../.agent/modules/python-uv.md).
