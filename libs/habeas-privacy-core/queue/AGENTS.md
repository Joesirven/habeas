> inherits: ../AGENTS.md

# AGENTS.md — habeas-privacy-core/queue/

Queue-as-table primitives: claim, heartbeat, reap, backoff, status transitions.

- Imported by apps and CLI — never import app code from here.
- No vendor-specific logic in this module.
