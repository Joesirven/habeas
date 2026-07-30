-- migrate:up
-- Per-system external vertical match/suppress attempt tables (ADR-11 / ADR-08).
-- Privacy-safe: audit_payload allowlisted JSONB only — no vendor PII blobs in Postgres.

CREATE TABLE mailchimp_attempts (
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
    CONSTRAINT mailchimp_attempts_step_valid
        CHECK (step IN ('matching', 'suppression')),
    CONSTRAINT mailchimp_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT mailchimp_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT mailchimp_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

COMMENT ON COLUMN mailchimp_attempts.audit_payload IS
    'Allowlisted external attempt audit (ids/counts/redacted errors only; no PII/hashes)';

CREATE INDEX ix_mailchimp_attempts_pending
    ON mailchimp_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER mailchimp_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON mailchimp_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

CREATE TABLE paylocity_attempts (
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
    CONSTRAINT paylocity_attempts_step_valid
        CHECK (step IN ('matching', 'suppression')),
    CONSTRAINT paylocity_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT paylocity_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT paylocity_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

COMMENT ON COLUMN paylocity_attempts.audit_payload IS
    'Allowlisted external attempt audit (ids/counts/redacted errors only; no PII/hashes)';

CREATE INDEX ix_paylocity_attempts_pending
    ON paylocity_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER paylocity_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON paylocity_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

CREATE TABLE lever_attempts (
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
    CONSTRAINT lever_attempts_step_valid
        CHECK (step IN ('matching', 'suppression')),
    CONSTRAINT lever_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT lever_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT lever_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

COMMENT ON COLUMN lever_attempts.audit_payload IS
    'Allowlisted external attempt audit (ids/counts/redacted errors only; no PII/hashes)';

CREATE INDEX ix_lever_attempts_pending
    ON lever_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER lever_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON lever_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

CREATE TABLE auth0_attempts (
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
    CONSTRAINT auth0_attempts_step_valid
        CHECK (step IN ('matching', 'suppression')),
    CONSTRAINT auth0_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT auth0_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT auth0_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

COMMENT ON COLUMN auth0_attempts.audit_payload IS
    'Allowlisted external attempt audit (ids/counts/redacted errors only; no PII/hashes)';

CREATE INDEX ix_auth0_attempts_pending
    ON auth0_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER auth0_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON auth0_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

CREATE TABLE google_sheets_attempts (
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
    CONSTRAINT google_sheets_attempts_step_valid
        CHECK (step IN ('matching', 'suppression')),
    CONSTRAINT google_sheets_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT google_sheets_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT google_sheets_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

COMMENT ON COLUMN google_sheets_attempts.audit_payload IS
    'Allowlisted external attempt audit (ids/counts/redacted errors only; no PII/hashes)';

CREATE INDEX ix_google_sheets_attempts_pending
    ON google_sheets_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER google_sheets_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON google_sheets_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

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

CREATE TABLE vertical_hash_refresh_attempts (
    id                  BIGSERIAL PRIMARY KEY,
    step                VARCHAR(20) NOT NULL DEFAULT 'refresh',
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    retry_after         TIMESTAMPTZ,
    worker_id           VARCHAR(100),
    claim_expires_at    TIMESTAMPTZ,
    submitted_at        TIMESTAMPTZ,
    error_code          VARCHAR(50),
    error_message       TEXT,
    system              VARCHAR(40) NOT NULL,
    CONSTRAINT vertical_hash_refresh_attempts_step_valid
        CHECK (step IN ('refresh')),
    CONSTRAINT vertical_hash_refresh_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT vertical_hash_refresh_attempts_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets'
        ))
);

CREATE INDEX ix_vertical_hash_refresh_attempts_pending
    ON vertical_hash_refresh_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE UNIQUE INDEX ix_vertical_hash_refresh_attempts_single_flight
    ON vertical_hash_refresh_attempts (system)
    WHERE status IN ('pending', 'claimed', 'in_flight');

CREATE TRIGGER vertical_hash_refresh_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON vertical_hash_refresh_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

CREATE TABLE vertical_hash_refresh_runs (
    id              BIGSERIAL PRIMARY KEY,
    attempt_id      BIGINT NOT NULL REFERENCES vertical_hash_refresh_attempts(id),
    status          VARCHAR(20) NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    rows_written    INT,
    error_message   TEXT,
    CONSTRAINT vertical_hash_refresh_runs_status_valid
        CHECK (status IN ('success', 'submit_error', 'outcome_error', 'timeout'))
);

CREATE INDEX ix_vertical_hash_refresh_runs_attempt
    ON vertical_hash_refresh_runs (attempt_id, finished_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON mailchimp_attempts FROM app_user;
        REVOKE UPDATE, DELETE ON paylocity_attempts FROM app_user;
        REVOKE UPDATE, DELETE ON lever_attempts FROM app_user;
        REVOKE UPDATE, DELETE ON auth0_attempts FROM app_user;
        REVOKE UPDATE, DELETE ON google_sheets_attempts FROM app_user;
        REVOKE UPDATE, DELETE ON cassandra_attempts FROM app_user;
        REVOKE UPDATE, DELETE ON vertical_hash_refresh_attempts FROM app_user;
        REVOKE UPDATE, DELETE ON vertical_hash_refresh_runs FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS mailchimp_attempts_terminal_guard ON mailchimp_attempts;
DROP TRIGGER IF EXISTS paylocity_attempts_terminal_guard ON paylocity_attempts;
DROP TRIGGER IF EXISTS lever_attempts_terminal_guard ON lever_attempts;
DROP TRIGGER IF EXISTS auth0_attempts_terminal_guard ON auth0_attempts;
DROP TRIGGER IF EXISTS google_sheets_attempts_terminal_guard ON google_sheets_attempts;
DROP TRIGGER IF EXISTS cassandra_attempts_terminal_guard ON cassandra_attempts;
DROP TRIGGER IF EXISTS vertical_hash_refresh_attempts_terminal_guard ON vertical_hash_refresh_attempts;

DROP TABLE IF EXISTS vertical_hash_refresh_runs;
DROP TABLE IF EXISTS vertical_hash_refresh_attempts;
DROP TABLE IF EXISTS cassandra_attempts;
DROP TABLE IF EXISTS google_sheets_attempts;
DROP TABLE IF EXISTS auth0_attempts;
DROP TABLE IF EXISTS lever_attempts;
DROP TABLE IF EXISTS paylocity_attempts;
DROP TABLE IF EXISTS mailchimp_attempts;
