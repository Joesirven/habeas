-- migrate:up
-- Slice A: identity verification, email templates, request documents (KTD-3–5).

CREATE TABLE request_identity_verifications (
    id              BIGSERIAL PRIMARY KEY,
    request_id      UUID NOT NULL REFERENCES requests(id),
    status          VARCHAR(20) NOT NULL,
    method          VARCHAR(50),
    verified_by     VARCHAR(200) NOT NULL,
    notes           TEXT,
    verified_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT request_identity_verifications_status_valid
        CHECK (status IN ('verified', 'failed', 'pending'))
);

CREATE INDEX ix_request_identity_verifications_request
    ON request_identity_verifications (request_id, verified_at DESC);

CREATE TABLE email_templates (
    id              BIGSERIAL PRIMARY KEY,
    slug            VARCHAR(80) NOT NULL,
    subject         TEXT NOT NULL,
    body            TEXT NOT NULL,
    placeholder_schema JSONB NOT NULL DEFAULT '[]'::jsonb,
    active          BOOLEAN NOT NULL DEFAULT true,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT email_templates_slug_unique UNIQUE (slug)
);

CREATE TABLE request_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      UUID NOT NULL REFERENCES requests(id),
    filename        VARCHAR(255) NOT NULL,
    content_type    VARCHAR(100) NOT NULL DEFAULT 'application/octet-stream',
    gcs_uri         TEXT NOT NULL,
    uploaded_by     VARCHAR(200) NOT NULL,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_request_documents_request
    ON request_documents (request_id, uploaded_at DESC);

ALTER TABLE authorized_agents
    ADD COLUMN IF NOT EXISTS expected_shape_profile VARCHAR(50) NOT NULL DEFAULT 'generic';

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON request_identity_verifications FROM app_user;
        REVOKE UPDATE, DELETE ON request_documents FROM app_user;
    END IF;
END $$;

INSERT INTO email_templates (slug, subject, body, placeholder_schema)
VALUES
    (
        'access_delivery',
        'Your California privacy access response',
        'Hello {{requestor_name}},\n\nYour access response is ready. Use this link (expires in ~30 days):\n{{shareable_url}}\n\n— Habeas Data Privacy',
        '["requestor_name", "shareable_url"]'::jsonb
    ),
    (
        'general_correspondence',
        'Regarding your privacy request',
        'Hello {{requestor_name}},\n\n{{address}}\n\n— Habeas Data Privacy',
        '["requestor_name", "address"]'::jsonb
    ),
    (
        'data_owner_outreach_hint',
        'Pending privacy queue items',
        'Hi — you have {{pending_count}} item(s) pending in the data privacy queue. Please review when you can.',
        '["pending_count", "owner_email"]'::jsonb
    )
ON CONFLICT (slug) DO NOTHING;

-- migrate:down
ALTER TABLE authorized_agents DROP COLUMN IF EXISTS expected_shape_profile;
DROP TABLE IF EXISTS request_documents;
DROP TABLE IF EXISTS email_templates;
DROP TABLE IF EXISTS request_identity_verifications;
