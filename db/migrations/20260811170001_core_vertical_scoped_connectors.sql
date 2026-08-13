-- migrate:up
-- Vertical-scoped connectors: catalog, owner assignments, mode history, system allowlist expand.

CREATE TABLE data_verticals (
    id              TEXT PRIMARY KEY,
    display_label   TEXT NOT NULL,
    view_only       BOOLEAN NOT NULL DEFAULT false,
    sort_order      INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE data_verticals IS
    'KD20 department-style data vertical catalog (communications, people_hr, tech, bizdev, data).';

CREATE TABLE vertical_system_bindings (
    vertical_id         TEXT NOT NULL REFERENCES data_verticals(id) ON DELETE CASCADE,
    system              TEXT NOT NULL,
    allowed_approaches  TEXT[] NOT NULL DEFAULT '{}'::text[],
    active              BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (vertical_id, system),
    CONSTRAINT vertical_system_bindings_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni'
        )),
    CONSTRAINT vertical_system_bindings_approaches_valid
        CHECK (
            allowed_approaches <@ ARRAY['live', 'upload']::text[]
        )
);

COMMENT ON TABLE vertical_system_bindings IS
    'Which connection systems belong to a vertical and which approaches (live/upload) are allowed.';

CREATE TABLE user_vertical_assignments (
    email       TEXT NOT NULL,
    vertical_id TEXT NOT NULL REFERENCES data_verticals(id) ON DELETE CASCADE,
    active      BOOLEAN NOT NULL DEFAULT true,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    added_by    TEXT,
    PRIMARY KEY (email, vertical_id)
);

COMMENT ON TABLE user_vertical_assignments IS
    'Vertical-scoped owner assignments; coarse data_owner role remains env allowlist.';

CREATE INDEX ix_user_vertical_assignments_vertical
    ON user_vertical_assignments (vertical_id)
    WHERE active = true;

CREATE TABLE connection_mode_events (
    id              BIGSERIAL PRIMARY KEY,
    connection_id   UUID NOT NULL REFERENCES integration_connections(id) ON DELETE CASCADE,
    from_mode       TEXT,
    to_mode         TEXT NOT NULL,
    actor           TEXT NOT NULL,
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT connection_mode_events_to_mode_valid
        CHECK (to_mode IN ('live', 'upload')),
    CONSTRAINT connection_mode_events_from_mode_valid
        CHECK (from_mode IS NULL OR from_mode IN ('live', 'upload'))
);

COMMENT ON TABLE connection_mode_events IS
    'Append-only history of Live/Upload mode changes for integration connections.';

CREATE INDEX ix_connection_mode_events_connection_id
    ON connection_mode_events (connection_id, created_at DESC);

REVOKE UPDATE, DELETE ON connection_mode_events FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON connection_mode_events FROM app_user;
    END IF;
END $$;

-- Expand integration_connections.system CHECK for upload-only systems.
ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS integration_connections_system_valid;

ALTER TABLE integration_connections
    ADD CONSTRAINT integration_connections_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni'
        ));

-- Expand vertical_hash_refresh_attempts.system CHECK (workers may no-op until later).
ALTER TABLE vertical_hash_refresh_attempts
    DROP CONSTRAINT IF EXISTS vertical_hash_refresh_attempts_system_valid;

ALTER TABLE vertical_hash_refresh_attempts
    ADD CONSTRAINT vertical_hash_refresh_attempts_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets',
            'bizdev_contacts', 'hr_alumni'
        ));

-- KD20 seed catalog
INSERT INTO data_verticals (id, display_label, view_only, sort_order) VALUES
    ('communications', 'Communications', false, 10),
    ('people_hr', 'People/HR', false, 20),
    ('tech', 'Tech', false, 30),
    ('bizdev', 'BizDev', false, 40),
    ('data', 'Data', true, 50)
ON CONFLICT (id) DO NOTHING;

INSERT INTO vertical_system_bindings (vertical_id, system, allowed_approaches) VALUES
    ('communications', 'mailchimp', ARRAY['live', 'upload']::text[]),
    ('people_hr', 'paylocity', ARRAY['upload', 'live']::text[]),
    ('people_hr', 'lever', ARRAY['live']::text[]),
    ('people_hr', 'hr_alumni', ARRAY['upload']::text[]),
    ('tech', 'auth0', ARRAY['live', 'upload']::text[]),
    ('bizdev', 'bizdev_contacts', ARRAY['upload']::text[]),
    ('data', 'cassandra', ARRAY[]::text[])
ON CONFLICT (vertical_id, system) DO NOTHING;

-- migrate:down
DELETE FROM vertical_system_bindings
 WHERE system IN ('bizdev_contacts', 'hr_alumni')
    OR vertical_id IN ('communications', 'people_hr', 'tech', 'bizdev', 'data');

DELETE FROM data_verticals
 WHERE id IN ('communications', 'people_hr', 'tech', 'bizdev', 'data');

DROP TABLE IF EXISTS connection_mode_events;
DROP TABLE IF EXISTS user_vertical_assignments;
DROP TABLE IF EXISTS vertical_system_bindings;
DROP TABLE IF EXISTS data_verticals;

ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS integration_connections_system_valid;

ALTER TABLE integration_connections
    ADD CONSTRAINT integration_connections_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra'
        ));

ALTER TABLE vertical_hash_refresh_attempts
    DROP CONSTRAINT IF EXISTS vertical_hash_refresh_attempts_system_valid;

ALTER TABLE vertical_hash_refresh_attempts
    ADD CONSTRAINT vertical_hash_refresh_attempts_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets'
        ));
