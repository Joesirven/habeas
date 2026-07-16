-- migrate:up
-- Stub ledger for notice lane (ADR-37). No sender worker in MVP.
CREATE TABLE communication_attempts (
    id              BIGSERIAL PRIMARY KEY,
    request_id      UUID NOT NULL REFERENCES requests(id),
    direction       VARCHAR(10) NOT NULL DEFAULT 'outbound',
    method          VARCHAR(20) NOT NULL,
    purpose         VARCHAR(30) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'recorded',
    contacted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    contacted_by    VARCHAR(200) NOT NULL,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT communication_attempts_direction_valid
        CHECK (direction IN ('outbound', 'inbound')),
    CONSTRAINT communication_attempts_status_valid
        CHECK (status IN ('recorded', 'pending', 'sent', 'failed'))
);

CREATE INDEX ix_communication_attempts_request
    ON communication_attempts (request_id, contacted_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON communication_attempts FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS communication_attempts;
