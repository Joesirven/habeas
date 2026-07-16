-- migrate:up
ALTER TABLE requests DROP CONSTRAINT IF EXISTS requests_intake_source_valid;

ALTER TABLE requests
    ADD CONSTRAINT requests_intake_source_valid
        CHECK (intake_source IN ('webform', 'drop', 'csv_batch', 'manual'));

-- migrate:down
ALTER TABLE requests DROP CONSTRAINT IF EXISTS requests_intake_source_valid;

ALTER TABLE requests
    ADD CONSTRAINT requests_intake_source_valid
        CHECK (intake_source IN ('webform', 'drop', 'csv_batch'));
