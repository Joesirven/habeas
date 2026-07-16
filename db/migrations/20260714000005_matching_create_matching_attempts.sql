-- migrate:up
CREATE TABLE matching_attempts (
    id                  BIGSERIAL PRIMARY KEY,
    request_id          UUID NOT NULL REFERENCES requests(id),
    step                VARCHAR(20) NOT NULL DEFAULT 'matching',
    attempt_number      INT NOT NULL DEFAULT 1,
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    retry_after         TIMESTAMPTZ,
    worker_id           VARCHAR(100),
    claim_expires_at    TIMESTAMPTZ,
    submitted_at        TIMESTAMPTZ,
    error_code          VARCHAR(50),
    error_message       TEXT,
    CONSTRAINT matching_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT matching_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT matching_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

CREATE INDEX ix_matching_attempts_pending
    ON matching_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER matching_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON matching_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON matching_attempts FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS matching_attempts_terminal_guard ON matching_attempts;
DROP TABLE IF EXISTS matching_attempts;
