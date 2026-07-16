-- migrate:up
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

-- migrate:down
DROP TABLE IF EXISTS intake_batches;
