-- migrate:up
-- Retire pre–ADR-32 batch/staging queue tables (collector scaffolds removed).
DROP TABLE IF EXISTS intake_staging_rows;
DROP TABLE IF EXISTS intake_batches;

-- migrate:down
CREATE TABLE intake_batches (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_source       VARCHAR(20) NOT NULL,
    gcs_uri             TEXT NOT NULL,
    authorized_agent_id UUID REFERENCES authorized_agents(id),
    status              VARCHAR(20) NOT NULL DEFAULT 'received',
    row_count           INT NOT NULL DEFAULT 0,
    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT intake_batches_source_valid
        CHECK (intake_source IN ('webform', 'drop', 'csv_batch', 'manual')),
    CONSTRAINT intake_batches_status_valid
        CHECK (status IN ('received', 'processing', 'completed', 'failed'))
);

CREATE INDEX ix_intake_batches_source_received
    ON intake_batches (intake_source, received_at DESC);

CREATE TABLE intake_staging_rows (
    id            BIGSERIAL PRIMARY KEY,
    batch_id      UUID NOT NULL REFERENCES intake_batches(id),
    row_number    INT NOT NULL,
    raw_row       JSONB NOT NULL,
    clean_status  VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_reason  TEXT,
    request_id    UUID REFERENCES requests(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT intake_staging_clean_status_valid
        CHECK (clean_status IN ('pending', 'cleaned', 'failed', 'promoted'))
);

CREATE INDEX ix_intake_staging_batch_status
    ON intake_staging_rows (batch_id, clean_status);
