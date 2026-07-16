-- migrate:up
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

-- migrate:down
DROP TABLE IF EXISTS intake_staging_rows;
