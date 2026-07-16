-- migrate:up
CREATE TABLE drop_raw_requests (
    id                      BIGSERIAL PRIMARY KEY,
    drop_record_id          TEXT NOT NULL,
    list_type               VARCHAR(10) NOT NULL,
    source_csv_filename     TEXT NOT NULL,
    raw_payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_status         SMALLINT,
    notice_review_status    VARCHAR(20) NOT NULL DEFAULT 'pending',
    response_file_name      TEXT,
    landed_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT drop_raw_requests_list_type_valid
        CHECK (list_type IN ('NDZ', 'Email', 'Phone')),
    CONSTRAINT drop_raw_requests_response_status_valid
        CHECK (response_status IS NULL OR response_status BETWEEN 2 AND 5),
    CONSTRAINT drop_raw_requests_notice_review_status_valid
        CHECK (notice_review_status IN ('pending', 'approved', 'rejected'))
);

CREATE INDEX ix_drop_raw_requests_source_csv_filename
    ON drop_raw_requests (source_csv_filename);

CREATE INDEX ix_drop_raw_requests_drop_record_id
    ON drop_raw_requests (drop_record_id);

CREATE TABLE drop_ingest_attempts (
    id                  BIGSERIAL PRIMARY KEY,
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
    gcs_uri             TEXT,
    source_csv_filename TEXT,
    list_type           VARCHAR(10),
    CONSTRAINT drop_ingest_attempts_step_valid
        CHECK (step IN ('land', 'promote')),
    CONSTRAINT drop_ingest_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT drop_ingest_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT drop_ingest_attempts_list_type_valid
        CHECK (list_type IS NULL OR list_type IN ('NDZ', 'Email', 'Phone'))
);

CREATE INDEX ix_drop_ingest_attempts_pending
    ON drop_ingest_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER drop_ingest_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON drop_ingest_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

CREATE TABLE drop_connector_attempts (
    id                  BIGSERIAL PRIMARY KEY,
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
    gcs_uri             TEXT,
    source_csv_filename TEXT,
    response_file_name  TEXT,
    file_suffix         TEXT,
    CONSTRAINT drop_connector_attempts_step_valid
        CHECK (step IN ('download', 'upload', 'amend')),
    CONSTRAINT drop_connector_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT drop_connector_attempts_attempt_positive
        CHECK (attempt_number >= 1)
);

CREATE INDEX ix_drop_connector_attempts_pending
    ON drop_connector_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER drop_connector_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON drop_connector_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

CREATE TABLE drop_response_submissions (
    id                   BIGSERIAL PRIMARY KEY,
    source_csv_filename  TEXT NOT NULL,
    response_file_name   TEXT NOT NULL,
    submission_type      VARCHAR(10) NOT NULL,
    submitted_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_count       INT,
    rejected_count       INT,
    error_detail         TEXT,
    connector_attempt_id BIGINT REFERENCES drop_connector_attempts(id),
    CONSTRAINT drop_response_submissions_type_valid
        CHECK (submission_type IN ('upload', 'amend'))
);

CREATE INDEX ix_drop_response_submissions_source_csv_filename
    ON drop_response_submissions (source_csv_filename, submitted_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON drop_raw_requests FROM app_user;
        REVOKE UPDATE, DELETE ON drop_ingest_attempts FROM app_user;
        REVOKE UPDATE, DELETE ON drop_connector_attempts FROM app_user;
        REVOKE UPDATE, DELETE ON drop_response_submissions FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS drop_response_submissions;
DROP TRIGGER IF EXISTS drop_connector_attempts_terminal_guard ON drop_connector_attempts;
DROP TABLE IF EXISTS drop_connector_attempts;
DROP TRIGGER IF EXISTS drop_ingest_attempts_terminal_guard ON drop_ingest_attempts;
DROP TABLE IF EXISTS drop_ingest_attempts;
DROP TABLE IF EXISTS drop_raw_requests;
