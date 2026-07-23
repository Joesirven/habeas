> inherits: ../AGENTS.md

# AGENTS.md — app/matching/

**Kind:** automation

Consumer record matching for privacy requests, across all intake sources — not DROP-only.

- One `MatchingPipeline` interface (`pipeline.py`); one adapter class per intake source in
  `adapters/` (`drop_hash.py`, `plaintext.py`); `router.py` dispatches by `IntakeSource`
  (`habeas_privacy_core.models.request.IntakeSource`). A new intake source or a new
  state-specific matching requirement is a new adapter + router entry, never a new app.
- `DropHashPipeline` looks up `hash_value` in BigQuery `example-gcp-project.drop_hash_index` marts
  (`email_hash` / `phone_hash` / `ndz_hash`; columns `hash_value`, `dwid`, `state`,
  `built_at`) with mandatory `state = @lookup_state` bound to the requester’s
  normalized `requests.requestor_state` (never hardcode CA; never return out-of-state
  DWIDs). Env `DROP_HASH_LOOKUP_STATE` is local/dev fallback only — production DROP
  path fails closed when `requestor_state` is missing. Persists
  `MatchResult.match_count` on `matching_results`.
- Matching attempts persist allowlisted `audit_payload` JSONB on success/error
  (adapter, duration, match_count, lookup_state, BQ table names, redacted errors —
  never hashes/dwids/emails/phones). Reaper `max_attempts` default is **5**
  (≥3 retries after the initial attempt).
- **Chunk drain (Method E):** queue stays one `matching_attempts` row per request.
  Hot path is set-based BigQuery (`lookup_dwids_by_hashes`) in ≤10K homogeneous
  chunks. `POST /ensure-drain` acquires singleton `matching_drain_lease` and starts
  Cloud Run Job `matching-drain-dev` (5 tasks → `python -m matching.chunk_drain`).
  Catch-all Scheduler hits `/ensure-drain` (not one-row `/process`). Small/ops path:
  `POST /process` still claims one row. Wave kick: admin-api after dispatch and after
  rematch-on-refresh. Logs/ops: ids/counts only (`matching_attempts.drain` on pipeline).
- Vendor adapter code in `adapters/` inside this app only — no top-level `adapters/`.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `matching_` as appropriate.
  Drain lease: `matching_create_matching_drain_lease`.
