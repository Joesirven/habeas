-- migrate:up
-- Per-Id upload/amend ledger so stragglers sharing a source filename can upload (KTD-9).
CREATE TABLE drop_response_submission_ids (
    id              BIGSERIAL PRIMARY KEY,
    submission_id   BIGINT NOT NULL REFERENCES drop_response_submissions(id),
    drop_record_id  TEXT NOT NULL,
    response_status INT NOT NULL,
    submission_type VARCHAR(10) NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT drop_response_submission_ids_type_valid
        CHECK (submission_type IN ('upload', 'amend'))
);

CREATE INDEX ix_drop_response_submission_ids_record
    ON drop_response_submission_ids (drop_record_id, submitted_at DESC);

CREATE INDEX ix_drop_response_submission_ids_submission
    ON drop_response_submission_ids (submission_id);

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON drop_response_submission_ids FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS drop_response_submission_ids;
