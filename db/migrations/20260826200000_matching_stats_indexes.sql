-- migrate:up
-- Matching stats + DROP response rollups. Expand-only for matching_results:
-- leave ix_matching_results_request; add covering sibling.

CREATE INDEX ix_matching_results_request_cover
    ON matching_results (request_id, recorded_at DESC)
    INCLUDE (matched, match_count, matched_via);

CREATE INDEX ix_drop_raw_requests_unresponded
    ON drop_raw_requests (id)
    WHERE response_status IS NULL;

CREATE INDEX ix_drop_raw_requests_list_type_response_status
    ON drop_raw_requests (list_type, response_status);

CREATE INDEX ix_approval_requests_action_pending
    ON approval_requests (action_type, status)
    WHERE status = 'pending';

CREATE INDEX ix_matching_attempts_status_matching
    ON matching_attempts (status)
    WHERE step = 'matching';

CREATE INDEX ix_matching_results_recorded_at_brin
    ON matching_results USING BRIN (recorded_at);

CREATE INDEX ix_requests_received_at_brin
    ON requests USING BRIN (received_at);

-- migrate:down
DROP INDEX IF EXISTS ix_requests_received_at_brin;
DROP INDEX IF EXISTS ix_matching_results_recorded_at_brin;
DROP INDEX IF EXISTS ix_matching_attempts_status_matching;
DROP INDEX IF EXISTS ix_approval_requests_action_pending;
DROP INDEX IF EXISTS ix_drop_raw_requests_list_type_response_status;
DROP INDEX IF EXISTS ix_drop_raw_requests_unresponded;
DROP INDEX IF EXISTS ix_matching_results_request_cover;
