> inherits: ../../AGENTS.md

# AGENTS.md — habeas-privacy-core/queue/

Queue-as-table primitives: claim, heartbeat, reap, backoff, status transitions.

- Imported by apps and CLI — never import app code from here.
- No vendor-specific logic in this module.
- Matching chunk drain: `claim_matching_chunk` (homogeneous ≤10K, `FOR UPDATE SKIP
  LOCKED`, stays `claimed`) and `drain_lease` helpers for singleton
  `matching_drain_lease` (acquire / renew / release / status). Attempt hang/retry
  remains reaper + lease TTL — drain lease is orchestration only, not the work queue.
