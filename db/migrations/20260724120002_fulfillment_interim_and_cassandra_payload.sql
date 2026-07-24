-- migrate:up
-- Slice B interim: interim_upload step + Cassandra payload column (KTD-10–14, DQ1).

ALTER TABLE data_fulfillment_attempts
    DROP CONSTRAINT IF EXISTS data_fulfillment_attempts_step_valid;

ALTER TABLE data_fulfillment_attempts
    ADD CONSTRAINT data_fulfillment_attempts_step_valid
        CHECK (step IN ('suppression', 'reproduction', 'interim_upload'));

ALTER TABLE data_fulfillment_attempts
    ADD COLUMN IF NOT EXISTS cassandra_request_payload JSONB;

COMMENT ON COLUMN data_fulfillment_attempts.cassandra_request_payload IS
    'Target suppression SSL API payload for audit/retry — no PII in logs (R25, DQ1).';

-- migrate:down
ALTER TABLE data_fulfillment_attempts
    DROP COLUMN IF EXISTS cassandra_request_payload;

ALTER TABLE data_fulfillment_attempts
    DROP CONSTRAINT IF EXISTS data_fulfillment_attempts_step_valid;

ALTER TABLE data_fulfillment_attempts
    ADD CONSTRAINT data_fulfillment_attempts_step_valid
        CHECK (step IN ('suppression', 'reproduction'));
