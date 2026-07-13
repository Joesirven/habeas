-- migrate:up
CREATE OR REPLACE FUNCTION core_forbid_terminal_attempt_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status IN ('success', 'submit_error', 'outcome_error', 'timeout', 'abandoned') THEN
        RAISE EXCEPTION 'terminal attempt rows are immutable (id=%)', OLD.id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE core_queue_test_attempts (
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
    CONSTRAINT core_queue_test_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT core_queue_test_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT core_queue_test_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

CREATE INDEX ix_core_queue_test_pending
    ON core_queue_test_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER core_queue_test_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON core_queue_test_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON core_queue_test_attempts FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS core_queue_test_attempts_terminal_guard ON core_queue_test_attempts;
DROP TABLE IF EXISTS core_queue_test_attempts;
DROP FUNCTION IF EXISTS core_forbid_terminal_attempt_mutation();
