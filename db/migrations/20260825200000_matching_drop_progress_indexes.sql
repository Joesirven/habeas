-- migrate:up
-- Bound GET /ops/drop/matching-progress: join drop requests + GROUP BY status
-- (collect_matching_progress polls every 750 ms–5 s during drain).

CREATE INDEX ix_matching_attempts_request_status
    ON matching_attempts (request_id, status);

CREATE INDEX ix_requests_drop_id
    ON requests (id)
    WHERE intake_source = 'drop';

-- migrate:down
DROP INDEX IF EXISTS ix_requests_drop_id;
DROP INDEX IF EXISTS ix_matching_attempts_request_status;
