-- migrate:up
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE requests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    intake_source   VARCHAR(20) NOT NULL,
    intake_batch_id UUID,
    requestor_state VARCHAR(2) NOT NULL,
    request_type    VARCHAR(20) NOT NULL,
    raw_payload     JSONB NOT NULL,
    pii_hash        BYTEA,
    CONSTRAINT requests_intake_source_valid
        CHECK (intake_source IN ('webform', 'drop', 'csv_batch'))
);

CREATE INDEX ix_requests_state_received
    ON requests (requestor_state, received_at);

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON requests FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS requests;
