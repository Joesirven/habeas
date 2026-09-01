-- migrate:up
-- Split google_sheets_attempts into per-catalog-system tables for Alumni and
-- Contact Us sheet workers (hr_alumni, bizdev_contacts). Retire the shared
-- google_sheets_attempts queue and repoint matching_drain_lease id 6/7.
--
-- Row routing (from google_sheets_attempts):
--   audit_payload.system = hr_alumni        → hr_alumni_attempts
--   audit_payload.system = bizdev_contacts  → bizdev_contacts_attempts
--   audit_payload.system absent or google_sheets (legacy):
--     audit_payload.vertical_id or vertical = bizdev → bizdev_contacts_attempts
--     otherwise → hr_alumni_attempts
-- Legacy rows with no resolvable vertical default to hr_alumni (Alumni was the
-- original sheet spine; orphan rows cannot be disambiguated further in SQL).

CREATE TABLE hr_alumni_attempts (
    id                      BIGSERIAL PRIMARY KEY,
    request_id              UUID NOT NULL REFERENCES requests(id),
    step                    VARCHAR(20) NOT NULL,
    attempt_number          INT NOT NULL DEFAULT 1,
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempted_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at            TIMESTAMPTZ,
    retry_after             TIMESTAMPTZ,
    worker_id               VARCHAR(100),
    claim_expires_at        TIMESTAMPTZ,
    submitted_at            TIMESTAMPTZ,
    error_code              VARCHAR(50),
    error_message           TEXT,
    audit_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    matched_external_id     VARCHAR,
    match_confidence        NUMERIC,
    suppression_method      VARCHAR,
    suppression_ref         VARCHAR,
    suppressed_at           TIMESTAMPTZ,
    external_ref            VARCHAR,
    CONSTRAINT hr_alumni_attempts_step_valid
        CHECK (step IN ('matching', 'suppression')),
    CONSTRAINT hr_alumni_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT hr_alumni_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT hr_alumni_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

COMMENT ON COLUMN hr_alumni_attempts.audit_payload IS
    'Allowlisted external attempt audit (ids/counts/redacted errors only; no PII/hashes)';

CREATE INDEX ix_hr_alumni_attempts_pending
    ON hr_alumni_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER hr_alumni_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON hr_alumni_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

CREATE TABLE bizdev_contacts_attempts (
    id                      BIGSERIAL PRIMARY KEY,
    request_id              UUID NOT NULL REFERENCES requests(id),
    step                    VARCHAR(20) NOT NULL,
    attempt_number          INT NOT NULL DEFAULT 1,
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempted_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at            TIMESTAMPTZ,
    retry_after             TIMESTAMPTZ,
    worker_id               VARCHAR(100),
    claim_expires_at        TIMESTAMPTZ,
    submitted_at            TIMESTAMPTZ,
    error_code              VARCHAR(50),
    error_message           TEXT,
    audit_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    matched_external_id     VARCHAR,
    match_confidence        NUMERIC,
    suppression_method      VARCHAR,
    suppression_ref         VARCHAR,
    suppressed_at           TIMESTAMPTZ,
    external_ref            VARCHAR,
    CONSTRAINT bizdev_contacts_attempts_step_valid
        CHECK (step IN ('matching', 'suppression')),
    CONSTRAINT bizdev_contacts_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT bizdev_contacts_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT bizdev_contacts_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

COMMENT ON COLUMN bizdev_contacts_attempts.audit_payload IS
    'Allowlisted external attempt audit (ids/counts/redacted errors only; no PII/hashes)';

CREATE INDEX ix_bizdev_contacts_attempts_pending
    ON bizdev_contacts_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER bizdev_contacts_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON bizdev_contacts_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON hr_alumni_attempts FROM app_user;
        REVOKE UPDATE, DELETE ON bizdev_contacts_attempts FROM app_user;
    END IF;
END $$;

INSERT INTO hr_alumni_attempts (
    id,
    request_id,
    step,
    attempt_number,
    status,
    attempted_at,
    completed_at,
    retry_after,
    worker_id,
    claim_expires_at,
    submitted_at,
    error_code,
    error_message,
    audit_payload,
    matched_external_id,
    match_confidence,
    suppression_method,
    suppression_ref,
    suppressed_at,
    external_ref
)
SELECT
    id,
    request_id,
    step,
    attempt_number,
    status,
    attempted_at,
    completed_at,
    retry_after,
    worker_id,
    claim_expires_at,
    submitted_at,
    error_code,
    error_message,
    audit_payload,
    matched_external_id,
    match_confidence,
    suppression_method,
    suppression_ref,
    suppressed_at,
    external_ref
FROM google_sheets_attempts
WHERE lower(COALESCE(audit_payload->>'system', 'google_sheets')) = 'hr_alumni'
   OR (
       lower(COALESCE(audit_payload->>'system', 'google_sheets')) = 'google_sheets'
       AND COALESCE(audit_payload->>'vertical_id', audit_payload->>'vertical', 'people_hr')
           <> 'bizdev'
   );

INSERT INTO bizdev_contacts_attempts (
    id,
    request_id,
    step,
    attempt_number,
    status,
    attempted_at,
    completed_at,
    retry_after,
    worker_id,
    claim_expires_at,
    submitted_at,
    error_code,
    error_message,
    audit_payload,
    matched_external_id,
    match_confidence,
    suppression_method,
    suppression_ref,
    suppressed_at,
    external_ref
)
SELECT
    id,
    request_id,
    step,
    attempt_number,
    status,
    attempted_at,
    completed_at,
    retry_after,
    worker_id,
    claim_expires_at,
    submitted_at,
    error_code,
    error_message,
    audit_payload,
    matched_external_id,
    match_confidence,
    suppression_method,
    suppression_ref,
    suppressed_at,
    external_ref
FROM google_sheets_attempts
WHERE lower(COALESCE(audit_payload->>'system', 'google_sheets')) = 'bizdev_contacts'
   OR (
       lower(COALESCE(audit_payload->>'system', 'google_sheets')) = 'google_sheets'
       AND COALESCE(audit_payload->>'vertical_id', audit_payload->>'vertical') = 'bizdev'
   );

SELECT setval(
    pg_get_serial_sequence('hr_alumni_attempts', 'id'),
    COALESCE((SELECT MAX(id) FROM hr_alumni_attempts), 1)
);

SELECT setval(
    pg_get_serial_sequence('bizdev_contacts_attempts', 'id'),
    COALESCE((SELECT MAX(id) FROM bizdev_contacts_attempts), 1)
);

DROP TRIGGER IF EXISTS google_sheets_attempts_terminal_guard ON google_sheets_attempts;
DROP INDEX IF EXISTS ix_google_sheets_attempts_pending;
DROP TABLE google_sheets_attempts;

DELETE FROM matching_drain_lease
 WHERE lease_key = 'google_sheets';

INSERT INTO matching_drain_lease (id, lease_key)
VALUES
    (6, 'hr_alumni'),
    (7, 'bizdev_contacts')
ON CONFLICT (lease_key) DO NOTHING;

COMMENT ON COLUMN matching_drain_lease.lease_key IS
    'Drain identity; data-drop=id1, auth0=id2, axios_headquarters/paylocity/lever/hr_alumni/bizdev_contacts parallel.';

-- migrate:down
-- Restore shared google_sheets_attempts and merge split rows back.

CREATE TABLE google_sheets_attempts (
    id                      BIGSERIAL PRIMARY KEY,
    request_id              UUID NOT NULL REFERENCES requests(id),
    step                    VARCHAR(20) NOT NULL,
    attempt_number          INT NOT NULL DEFAULT 1,
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempted_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at            TIMESTAMPTZ,
    retry_after             TIMESTAMPTZ,
    worker_id               VARCHAR(100),
    claim_expires_at        TIMESTAMPTZ,
    submitted_at            TIMESTAMPTZ,
    error_code              VARCHAR(50),
    error_message           TEXT,
    audit_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    matched_external_id     VARCHAR,
    match_confidence        NUMERIC,
    suppression_method      VARCHAR,
    suppression_ref         VARCHAR,
    suppressed_at           TIMESTAMPTZ,
    external_ref            VARCHAR,
    CONSTRAINT google_sheets_attempts_step_valid
        CHECK (step IN ('matching', 'suppression')),
    CONSTRAINT google_sheets_attempts_status_valid
        CHECK (status IN (
            'pending', 'claimed', 'in_flight',
            'success', 'submit_error', 'outcome_error', 'timeout', 'abandoned'
        )),
    CONSTRAINT google_sheets_attempts_attempt_positive
        CHECK (attempt_number >= 1),
    CONSTRAINT google_sheets_attempts_unique_attempt
        UNIQUE (request_id, step, attempt_number)
);

COMMENT ON COLUMN google_sheets_attempts.audit_payload IS
    'Allowlisted external attempt audit (ids/counts/redacted errors only; no PII/hashes)';

INSERT INTO google_sheets_attempts (
    id,
    request_id,
    step,
    attempt_number,
    status,
    attempted_at,
    completed_at,
    retry_after,
    worker_id,
    claim_expires_at,
    submitted_at,
    error_code,
    error_message,
    audit_payload,
    matched_external_id,
    match_confidence,
    suppression_method,
    suppression_ref,
    suppressed_at,
    external_ref
)
SELECT
    id,
    request_id,
    step,
    attempt_number,
    status,
    attempted_at,
    completed_at,
    retry_after,
    worker_id,
    claim_expires_at,
    submitted_at,
    error_code,
    error_message,
    audit_payload,
    matched_external_id,
    match_confidence,
    suppression_method,
    suppression_ref,
    suppressed_at,
    external_ref
FROM hr_alumni_attempts
UNION ALL
SELECT
    id,
    request_id,
    step,
    attempt_number,
    status,
    attempted_at,
    completed_at,
    retry_after,
    worker_id,
    claim_expires_at,
    submitted_at,
    error_code,
    error_message,
    audit_payload,
    matched_external_id,
    match_confidence,
    suppression_method,
    suppression_ref,
    suppressed_at,
    external_ref
FROM bizdev_contacts_attempts;

SELECT setval(
    pg_get_serial_sequence('google_sheets_attempts', 'id'),
    COALESCE((SELECT MAX(id) FROM google_sheets_attempts), 1)
);

CREATE INDEX ix_google_sheets_attempts_pending
    ON google_sheets_attempts (step, attempted_at)
    WHERE status = 'pending';

CREATE TRIGGER google_sheets_attempts_terminal_guard
    BEFORE UPDATE OR DELETE ON google_sheets_attempts
    FOR EACH ROW EXECUTE FUNCTION core_forbid_terminal_attempt_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON google_sheets_attempts FROM app_user;
    END IF;
END $$;

DROP TRIGGER IF EXISTS hr_alumni_attempts_terminal_guard ON hr_alumni_attempts;
DROP TRIGGER IF EXISTS bizdev_contacts_attempts_terminal_guard ON bizdev_contacts_attempts;
DROP INDEX IF EXISTS ix_hr_alumni_attempts_pending;
DROP INDEX IF EXISTS ix_bizdev_contacts_attempts_pending;
DROP TABLE IF EXISTS hr_alumni_attempts;
DROP TABLE IF EXISTS bizdev_contacts_attempts;

DELETE FROM matching_drain_lease
 WHERE lease_key IN ('hr_alumni', 'bizdev_contacts');

INSERT INTO matching_drain_lease (id, lease_key)
VALUES (6, 'google_sheets')
ON CONFLICT (lease_key) DO NOTHING;

COMMENT ON COLUMN matching_drain_lease.lease_key IS
    'Drain identity; data-drop=id1, auth0=id2, axios_headquarters/paylocity/lever/google_sheets parallel.';
