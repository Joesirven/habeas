-- migrate:up
CREATE TABLE hash_index_refresh_attempts (
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
    state               VARCHAR(2) NOT NULL,
    list_types          TEXT[] NOT NULL,
    CONSTRAINT hash_index_refresh_attempts_step_valid
        CHECK (step IN ('refresh')),
    CONSTRAINT hash_index_refresh_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT hash_index_refresh_attempts_list_types_nonempty
        CHECK (cardinality(list_types) >= 1),
    CONSTRAINT hash_index_refresh_attempts_list_types_valid
        CHECK (list_types <@ ARRAY['NDZ', 'Email', 'Phone']::text[])
);

CREATE INDEX ix_hash_index_refresh_attempts_pending
    ON hash_index_refresh_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE UNIQUE INDEX ix_hash_index_refresh_attempts_single_flight
    ON hash_index_refresh_attempts (state)
    WHERE status IN ('pending', 'claimed', 'in_flight');

CREATE TRIGGER hash_index_refresh_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON hash_index_refresh_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

CREATE TABLE hash_index_refresh_runs (
    id                      BIGSERIAL PRIMARY KEY,
    attempt_id              BIGINT NOT NULL REFERENCES hash_index_refresh_attempts(id),
    status                  VARCHAR(20) NOT NULL,
    started_at              TIMESTAMPTZ NOT NULL,
    finished_at             TIMESTAMPTZ,
    rows_email              INT,
    rows_phone              INT,
    rows_ndz                INT,
    error_message           TEXT,
    rematch_enqueued_count  INT NOT NULL DEFAULT 0,
    CONSTRAINT hash_index_refresh_runs_status_valid
        CHECK (status IN ('success', 'submit_error', 'outcome_error', 'timeout'))
);

CREATE INDEX ix_hash_index_refresh_runs_attempt
    ON hash_index_refresh_runs (attempt_id, finished_at DESC);

ALTER TABLE matching_results
    ADD COLUMN match_count INT NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON hash_index_refresh_attempts FROM app_user;
        REVOKE UPDATE, DELETE ON hash_index_refresh_runs FROM app_user;
        REVOKE UPDATE, DELETE ON matching_results FROM app_user;
    END IF;
END $$;

-- migrate:down
ALTER TABLE matching_results DROP COLUMN IF EXISTS match_count;
DROP TABLE IF EXISTS hash_index_refresh_runs;
DROP TRIGGER IF EXISTS hash_index_refresh_attempts_terminal_guard ON hash_index_refresh_attempts;
DROP TABLE IF EXISTS hash_index_refresh_attempts;
