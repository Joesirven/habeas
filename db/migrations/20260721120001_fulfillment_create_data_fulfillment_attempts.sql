-- migrate:up
-- Restore request_type for access vs delete/opt_out fulfillment routing (ADR-32).
ALTER TABLE requests
    ADD COLUMN IF NOT EXISTS request_type VARCHAR(20) NOT NULL DEFAULT 'delete';

COMMENT ON COLUMN requests.request_type IS
    'Request purpose: delete, access, opt_out (ADR-32). Combined types may run both fulfill paths.';

CREATE TABLE data_fulfillment_attempts (
    id                  BIGSERIAL PRIMARY KEY,
    request_id          UUID NOT NULL REFERENCES requests(id),
    step                VARCHAR(20) NOT NULL,
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
    matching_result_id  BIGINT REFERENCES matching_results(id),
    bulk_process_id     TEXT,
    gcs_uri             TEXT,
    audit_payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT data_fulfillment_attempts_step_valid
        CHECK (step IN ('suppression', 'reproduction')),
    CONSTRAINT data_fulfillment_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT data_fulfillment_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT data_fulfillment_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

COMMENT ON COLUMN data_fulfillment_attempts.audit_payload IS
    'Allowlisted fulfillment audit (ids/counts/redacted errors only; no PII/hashes/dwids)';

CREATE INDEX ix_data_fulfillment_attempts_pending
    ON data_fulfillment_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE INDEX ix_data_fulfillment_attempts_request
    ON data_fulfillment_attempts (request_id, step, attempted_at DESC);

CREATE TRIGGER data_fulfillment_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON data_fulfillment_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON data_fulfillment_attempts FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS data_fulfillment_attempts_terminal_guard ON data_fulfillment_attempts;
DROP TABLE IF EXISTS data_fulfillment_attempts;
ALTER TABLE requests DROP COLUMN IF EXISTS request_type;
