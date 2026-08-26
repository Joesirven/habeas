> inherits: ../../AGENTS.md

# AGENTS.md — src/habeas_privacy_core/db/

asyncpg connection pool and table helpers (`pool.py`, `requests.py`, `hash_index_refresh.py`, `rematch.py`, `migrations.py`). Raw SQL only — no object-relational mapper.

- Imported by apps and CLI — never import app code from here.
- Thin `requests` spine retains `requestor_state` for matching/rematch (U20/U21);
  `insert_request` / `load_request_row` write and read it (normalized USPS).
- `requests` is insert-only (`core_forbid_requests_mutation`). Close → `request_closures`;
  deadline overrides → `request_due_overrides`; derive open/due via
  `habeas_privacy_core.db.request_lifecycle` SQL fragments.
- Postgres owns the hash index refresh queue (`enqueue_hash_index_refresh`, `claim_hash_index_refresh`).
- Hash index refresh attempts are immutable/auditable: no DELETE; updates only via
  queue lifecycle transitions; tests free single-flight by abandoning non-terminal rows.
- Rematch (`enqueue_rematch_for_refresh`, MVP `vertical=drop`): DROP whose
  normalized `requestor_state` equals the refreshed state, with latest result
  missing / `match_count = 0` or `> 1`, and `response_status IS NULL` **or**
  fulfilled Opted-out (`response_status = 4`). Status-4 candidates are
  **reopened** (`response_status → NULL`) in the same transaction; pending
  `matching.review` rows for those request_ids are superseded (rejected).
  Skips single-match (`match_count = 1`) and other fulfilled statuses (3, 5, …).
- `enqueue_hash_index_refresh_all_states` enqueues one attempt per served state
  (single-flight reuse when non-terminal already exists).
- State codes for enqueue/rematch use `habeas_privacy_core.geo.normalize_state_acronym`
  (USPS 50+DC allowlist; A10 until Jose confirms Q6).
- Header collectors (pipeline summary / matching-progress / console snapshot) must set `statement_timeout` on the acquired connection and must not JOIN `requests` for matching-progress (`GROUP BY matching_attempts.status` only).
- No vendor-specific logic in this module.
