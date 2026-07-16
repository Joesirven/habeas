-- migrate:up
-- Dev spine migration: truncate dependent rows before reshaping requests (ADR-33).
TRUNCATE TABLE
    matching_results,
    matching_attempts,
    approval_requests,
    core_workflow_test_attempts,
    core_queue_test_attempts,
    intake_staging_rows,
    requests
CASCADE;

DROP INDEX IF EXISTS ix_requests_state_received;

ALTER TABLE requests
    DROP COLUMN IF EXISTS intake_batch_id,
    DROP COLUMN IF EXISTS requestor_state,
    DROP COLUMN IF EXISTS request_type,
    DROP COLUMN IF EXISTS raw_payload,
    DROP COLUMN IF EXISTS pii_hash;

ALTER TABLE requests
    ADD COLUMN IF NOT EXISTS raw_record_id BIGINT;

ALTER TABLE requests DROP CONSTRAINT IF EXISTS requests_intake_source_valid;

ALTER TABLE requests
    ADD CONSTRAINT requests_intake_source_valid
        CHECK (intake_source IN ('drop', 'manual', 'webform', 'csv'));

CREATE INDEX ix_requests_intake_source_received
    ON requests (intake_source, received_at DESC);

CREATE OR REPLACE FUNCTION core_validate_requests_raw_fk()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.raw_record_id IS NULL THEN
        IF NEW.intake_source = 'manual' THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'raw_record_id required for intake_source=%', NEW.intake_source;
    END IF;

    CASE NEW.intake_source
        WHEN 'drop' THEN
            IF NOT EXISTS (
                SELECT 1 FROM drop_raw_requests WHERE id = NEW.raw_record_id
            ) THEN
                RAISE EXCEPTION
                    'raw_record_id % not found in drop_raw_requests',
                    NEW.raw_record_id;
            END IF;
        WHEN 'manual' THEN
            IF NOT EXISTS (
                SELECT 1 FROM manual_raw_requests WHERE id = NEW.raw_record_id
            ) THEN
                RAISE EXCEPTION
                    'raw_record_id % not found in manual_raw_requests',
                    NEW.raw_record_id;
            END IF;
        WHEN 'webform' THEN
            RAISE EXCEPTION
                'intake_source=webform raw FK not wired until webform_raw_requests exists';
        WHEN 'csv' THEN
            RAISE EXCEPTION
                'intake_source=csv raw FK not wired until csv_raw_requests exists';
        ELSE
            RAISE EXCEPTION 'unknown intake_source=%', NEW.intake_source;
    END CASE;

    RETURN NEW;
END;
$$;

CREATE TRIGGER requests_validate_raw_fk
    BEFORE INSERT OR UPDATE OF intake_source, raw_record_id ON requests
    FOR EACH ROW EXECUTE FUNCTION core_validate_requests_raw_fk();

-- migrate:down
DROP TRIGGER IF EXISTS requests_validate_raw_fk ON requests;
DROP FUNCTION IF EXISTS core_validate_requests_raw_fk();

DROP INDEX IF EXISTS ix_requests_intake_source_received;

ALTER TABLE requests DROP CONSTRAINT IF EXISTS requests_intake_source_valid;

ALTER TABLE requests
    DROP COLUMN IF EXISTS raw_record_id;

ALTER TABLE requests
    ADD COLUMN IF NOT EXISTS intake_batch_id UUID,
    ADD COLUMN IF NOT EXISTS requestor_state VARCHAR(2) NOT NULL DEFAULT 'CA',
    ADD COLUMN IF NOT EXISTS request_type VARCHAR(20) NOT NULL DEFAULT 'delete',
    ADD COLUMN IF NOT EXISTS raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS pii_hash BYTEA;

ALTER TABLE requests
    ADD CONSTRAINT requests_intake_source_valid
        CHECK (intake_source IN ('webform', 'drop', 'csv_batch', 'manual'));

CREATE INDEX ix_requests_state_received
    ON requests (requestor_state, received_at);
