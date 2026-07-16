-- migrate:up
CREATE TABLE matching_results (
    id           BIGSERIAL PRIMARY KEY,
    attempt_id   BIGINT NOT NULL REFERENCES matching_attempts(id),
    request_id   UUID NOT NULL REFERENCES requests(id),
    matched      BOOLEAN NOT NULL,
    consumer_id  VARCHAR(100),
    confidence   NUMERIC(5, 4),
    matched_via  VARCHAR(50) NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_matching_results_request
    ON matching_results (request_id, recorded_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON matching_results FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS matching_results;
