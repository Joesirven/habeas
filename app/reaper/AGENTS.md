> inherits: ../AGENTS.md

# AGENTS.md — app/reaper/

**Kind:** automation

Shared worker — releases expired leases, marks timeouts, inserts retry rows across request-grain queue tables. `hash_index_refresh_attempts` and `vertical_hash_refresh_attempts` are registered with `supports_attempt_retry=False` (lease / stuck-in-flight only; operator re-enqueue).

- Runs every minute; system-agnostic
- `matching_attempts` uses default `ReapedTableConfig.max_attempts=5`
  (initial attempt + ≥3 retries before terminal failure)
- Also reaps vertical attempt tables: `mailchimp_attempts`, `paylocity_attempts`,
  `lever_attempts`, `auth0_attempts`, `google_sheets_attempts`, `cassandra_attempts`,
  `axios_headquarters_attempts`
- On each `/reap`, merges `ops_retry_config` overrides when the table exists
  (Health Configuration PATCH; floor 4)
- Also runs `reconcile_ungated_matching_reviews` to backfill missing
  `matching.review` gates (match success opens the gate in-transaction)

- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `reaper_` or `matching_` as appropriate.
