-- migrate:up
CREATE TABLE manual_raw_requests (
    id              BIGSERIAL PRIMARY KEY,
    cleaned_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE manual_ingest_attempts (
    id                  BIGSERIAL PRIMARY KEY,
    raw_record_id       BIGINT REFERENCES manual_raw_requests(id),
    step                VARCHAR(20) NOT NULL DEFAULT 'promote',
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
    CONSTRAINT manual_ingest_attempts_step_valid
        CHECK (step IN ('promote')),
    CONSTRAINT manual_ingest_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT manual_ingest_attempts_attempt_positive
        CHECK (attempt_number >= 1)
);

CREATE INDEX ix_manual_ingest_attempts_pending
    ON manual_ingest_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER manual_ingest_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON manual_ingest_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON manual_raw_requests FROM app_user;
        REVOKE UPDATE, DELETE ON manual_ingest_attempts FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS manual_ingest_attempts_terminal_guard ON manual_ingest_attempts;
DROP TABLE IF EXISTS manual_ingest_attempts;
DROP TABLE IF EXISTS manual_raw_requests;
