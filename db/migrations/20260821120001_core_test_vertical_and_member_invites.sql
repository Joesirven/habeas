-- migrate:up
-- Test vertical (owner-inbox simulation) + data_user invites + /me pending settings.

INSERT INTO data_verticals (id, display_label, view_only, sort_order) VALUES
    ('test', 'Test vertical', false, 60)
ON CONFLICT (id) DO NOTHING;

INSERT INTO vertical_system_bindings (vertical_id, system, allowed_approaches) VALUES
    ('test', 'cassandra', ARRAY[]::text[])
ON CONFLICT (vertical_id, system) DO NOTHING;

ALTER TABLE user_vertical_assignments
    ADD COLUMN IF NOT EXISTS assignment_role TEXT NOT NULL DEFAULT 'data_owner';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'user_vertical_assignments_role_valid'
    ) THEN
        ALTER TABLE user_vertical_assignments
            ADD CONSTRAINT user_vertical_assignments_role_valid
            CHECK (assignment_role IN ('data_owner', 'data_user'));
    END IF;
END $$;

COMMENT ON COLUMN user_vertical_assignments.assignment_role IS
    'data_owner configures the vertical; data_user reviews, fulfills, and refreshes.';

CREATE TABLE IF NOT EXISTS vertical_member_invites (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vertical_id     TEXT NOT NULL REFERENCES data_verticals(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,
    invitee_email   TEXT NOT NULL,
    invitee_role    TEXT NOT NULL DEFAULT 'data_user',
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT vertical_member_invites_role_valid
        CHECK (invitee_role IN ('data_user'))
);

COMMENT ON TABLE vertical_member_invites IS
    'Owner-minted data_user invites; store SHA-256 hash only, never raw token.';

CREATE INDEX IF NOT EXISTS ix_vertical_member_invites_vertical_id
    ON vertical_member_invites (vertical_id);

CREATE INDEX IF NOT EXISTS ix_vertical_member_invites_token_hash
    ON vertical_member_invites (token_hash);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS settings_json JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN users.settings_json IS
    'Allowlisted first-run / pending-settings flags (no PII). Keys such as invite_data_users.';

-- migrate:down
ALTER TABLE users DROP COLUMN IF EXISTS settings_json;

DROP TABLE IF EXISTS vertical_member_invites;

ALTER TABLE user_vertical_assignments
    DROP CONSTRAINT IF EXISTS user_vertical_assignments_role_valid;

ALTER TABLE user_vertical_assignments
    DROP COLUMN IF EXISTS assignment_role;

DELETE FROM vertical_system_bindings
 WHERE vertical_id = 'test';

DELETE FROM data_verticals
 WHERE id = 'test';
