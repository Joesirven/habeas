-- migrate:up
-- KTD10/R16: intake_source='drop' is suppression-only — reject access/combined
-- request_type at the DB layer (defense-in-depth behind the app-level guard
-- in insert_request). CA DROP -> delete happy path is unaffected.
-- NOT VALID + VALIDATE: add without blocking full-table rewrite on apply;
-- VALIDATE scans existing rows and fails loudly if any legacy drop+access remain.
ALTER TABLE requests
    ADD CONSTRAINT requests_drop_reject_access_valid
        CHECK (NOT (intake_source = 'drop' AND request_type IN ('access', 'combined')))
        NOT VALID;
ALTER TABLE requests
    VALIDATE CONSTRAINT requests_drop_reject_access_valid;

-- migrate:down
ALTER TABLE requests DROP CONSTRAINT IF EXISTS requests_drop_reject_access_valid;
