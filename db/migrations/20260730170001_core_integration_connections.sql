-- migrate:up
-- Super-admin integration connections and owner invite tokens (connections onboarding).

CREATE TABLE integration_connections (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    system                  TEXT NOT NULL,
    display_name            TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pending',
    owner_email             TEXT,
    secret_resource_name    TEXT,
    last_tested_at          TIMESTAMPTZ,
    last_test_ok            BOOLEAN,
    last_test_detail        TEXT,
    created_by              TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT integration_connections_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra'
        )),
    CONSTRAINT integration_connections_status_valid
        CHECK (status IN (
            'pending', 'invited', 'connected', 'failed', 'revoked', 'infra_pending'
        ))
);

COMMENT ON TABLE integration_connections IS
    'Per-system integration connection registry; secrets live in Secret Manager, not Postgres.';
COMMENT ON COLUMN integration_connections.last_test_detail IS
    'Allowlisted short test result code only — never secrets or vendor payloads.';
COMMENT ON COLUMN integration_connections.metadata IS
    'Non-secret connection metadata (e.g. spreadsheet_id, public company_id).';

CREATE INDEX ix_integration_connections_system
    ON integration_connections (system);

CREATE INDEX ix_integration_connections_status
    ON integration_connections (status);

CREATE TABLE connection_invites (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id   UUID NOT NULL REFERENCES integration_connections(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,
    owner_email     TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE connection_invites IS
    'Short-lived owner invite tokens; store SHA-256 hash only, never raw token.';

CREATE INDEX ix_connection_invites_connection_id
    ON connection_invites (connection_id);

CREATE INDEX ix_connection_invites_token_hash
    ON connection_invites (token_hash);

-- migrate:down
DROP TABLE IF EXISTS connection_invites;
DROP TABLE IF EXISTS integration_connections;
