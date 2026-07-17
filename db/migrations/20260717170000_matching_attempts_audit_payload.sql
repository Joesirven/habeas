-- migrate:up
ALTER TABLE matching_attempts
    ADD COLUMN IF NOT EXISTS audit_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN matching_attempts.audit_payload IS
    'Allowlisted matching attempt audit (ids/counts/redacted errors only; no PII/hashes/dwids)';

-- migrate:down
ALTER TABLE matching_attempts
    DROP COLUMN IF EXISTS audit_payload;
