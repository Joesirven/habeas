-- migrate:up
-- Cassandra data-vertical suppression attempt queue (step=suppression only).
-- Privacy-safe: audit_payload allowlisted JSONB only — no vendor PII blobs in Postgres.

CREATE TABLE cassandra_attempts (
    id                      BIGSERIAL PRIMARY KEY,
    request_id              UUID NOT NULL REFERENCES requests(id),
    step                    VARCHAR(20) NOT NULL,
    attempt_number          INT NOT NULL DEFAULT 1,
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempted_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at            TIMESTAMPTZ,
    retry_after             TIMESTAMPTZ,
    worker_id               VARCHAR(100),
    claim_expires_at        TIMESTAMPTZ,
    submitted_at            TIMESTAMPTZ,
    error_code              VARCHAR(50),
    error_message           TEXT,
    audit_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    matched_external_id     VARCHAR,
    match_confidence        NUMERIC,
    suppression_method      VARCHAR,
    suppression_ref         VARCHAR,
    suppressed_at           TIMESTAMPTZ,
    external_ref            VARCHAR,
    CONSTRAINT cassandra_attempts_step_valid
        CHECK (step IN ('suppression')),
    CONSTRAINT cassandra_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT cassandra_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT cassandra_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

COMMENT ON COLUMN cassandra_attempts.audit_payload IS
    'Allowlisted external attempt audit (ids/counts/redacted errors only; no PII/hashes)';

CREATE INDEX ix_cassandra_attempts_pending
    ON cassandra_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER cassandra_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON cassandra_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON cassandra_attempts FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS cassandra_attempts_terminal_guard ON cassandra_attempts;
DROP TABLE IF EXISTS cassandra_attempts;
