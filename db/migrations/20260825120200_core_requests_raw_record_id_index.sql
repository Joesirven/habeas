-- migrate:up
CREATE INDEX IF NOT EXISTS ix_requests_raw_record_id ON requests (raw_record_id);

-- migrate:down
DROP INDEX IF EXISTS ix_requests_raw_record_id;
