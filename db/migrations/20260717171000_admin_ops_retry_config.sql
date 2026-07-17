-- migrate:up
CREATE TABLE IF NOT EXISTS ops_retry_config (
    table_name      TEXT PRIMARY KEY,
    max_attempts    INT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by      TEXT,
    CONSTRAINT ops_retry_config_max_attempts_floor
        CHECK (max_attempts >= 4)
);

COMMENT ON TABLE ops_retry_config IS
    'Per-attempt-table max_attempts overrides for Health Configuration (U24); floor 4';

-- migrate:down
DROP TABLE IF EXISTS ops_retry_config;
