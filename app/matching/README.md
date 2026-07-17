# Matching

Consumer record matching for privacy requests, across all intake sources. A `MatchingPipeline`
interface with one adapter per source — `DropHashPipeline` (DROP: SHA-256 compare against the
BigQuery hash-index marts) and `PlaintextMatchPipeline` (webform / CSV: plaintext lookup, data
source TBD — MDR vs M Tool) — dispatched by a router keyed on `IntakeSource`. A future
state-specific matching requirement is a new adapter class, not a new app.

## DROP hash lookup

- Looks up `hash_value` in `example-gcp-project.drop_hash_index` (`email_hash` / `phone_hash` /
  `ndz_hash`) with mandatory `state = @lookup_state` bound to the requester’s normalized
  `requestor_state` (never hardcode California; never return out-of-state DWIDs).
- Persists `MatchResult.match_count` and an allowlisted `audit_payload` JSONB on each attempt
  (adapter, duration, match_count, lookup_state, BQ tables, redacted errors — no hashes/dwids/PII).
- Reaper default `max_attempts` is **5** (≥3 retries after the initial attempt); Health
  Configuration may override via admin_api (floor 4).

## Local

```bash
uv sync --package matching-worker
uv run --package matching-worker uvicorn matching.main:app \
  --reload --app-dir app/matching/src --port 8084
```

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
**Design:** `Projects/Data Privacy/01-ARCHITECTURE/Decisions/ADR-21-DROP-Hash-Matching.md` (Addendum, 2026-07-13) + `05-DELIVERABLES/Matching-Design-Brief.md` in the KB.
