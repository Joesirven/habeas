-- migrate:up
CREATE TABLE admin_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    actor           VARCHAR(200) NOT NULL,
    interface       VARCHAR(20) NOT NULL,
    command         VARCHAR(200) NOT NULL,
    arguments       JSONB,
    result_status   INT,
    result_summary  TEXT,
    trace_id        VARCHAR(200),
    duration_ms     INT,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT admin_audit_log_interface_valid
        CHECK (interface IN ('admin-api', 'cli'))
);

CREATE INDEX idx_admin_audit_actor ON admin_audit_log(actor, occurred_at);
CREATE INDEX idx_admin_audit_command ON admin_audit_log(command, occurred_at);

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON admin_audit_log FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS admin_audit_log;
