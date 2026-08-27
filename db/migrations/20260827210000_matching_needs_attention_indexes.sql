-- migrate:up transaction:false
-- Bound GET /ops/requests/needs-attention?kind=matching (182s on prod with
-- ~1.84M rows in approval_requests / matching_results). latest_review runs
-- DISTINCT ON (request_id) over approval_requests filtered by action_type,
-- ordered by requested_at DESC; no existing index supports that ordering, so
-- Postgres full-scans + sorts the table on every inbox load.
-- CONCURRENTLY because prod tables are write-hot (plain CREATE INDEX would
-- block inserts for the duration); transaction:false is required for it.
--
-- Deliberately no new matching_results index: ix_matching_results_request
-- (20260714000006) is already (request_id, recorded_at DESC) — the exact key
-- the plan proposed re-adding — and ix_matching_results_request_cover
-- (20260826200000) adds INCLUDE (matched, match_count, matched_via), an
-- index-only scan for the latest_mr CTE. A third same-key index would only
-- tax writes.

CREATE INDEX CONCURRENTLY ix_approval_requests_action_request_requested
    ON approval_requests (action_type, request_id, requested_at DESC);

-- migrate:down
DROP INDEX IF EXISTS ix_approval_requests_action_request_requested;
