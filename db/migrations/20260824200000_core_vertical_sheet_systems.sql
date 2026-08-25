-- migrate:up
-- Dedicated Google Sheet systems: HR alumni sheet + BizDev Contact Us sheet.

ALTER TABLE vertical_system_bindings
    DROP CONSTRAINT IF EXISTS vertical_system_bindings_system_valid;

ALTER TABLE vertical_system_bindings
    ADD CONSTRAINT vertical_system_bindings_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni', 'axios_hq',
            'alumni_google_sheet', 'contact_us_google_sheet'
        ));

ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS integration_connections_system_valid;

ALTER TABLE integration_connections
    ADD CONSTRAINT integration_connections_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni', 'axios_hq',
            'alumni_google_sheet', 'contact_us_google_sheet'
        ));

ALTER TABLE vertical_hash_refresh_attempts
    DROP CONSTRAINT IF EXISTS vertical_hash_refresh_attempts_system_valid;

ALTER TABLE vertical_hash_refresh_attempts
    ADD CONSTRAINT vertical_hash_refresh_attempts_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets',
            'bizdev_contacts', 'hr_alumni', 'axios_hq',
            'alumni_google_sheet', 'contact_us_google_sheet'
        ));

INSERT INTO vertical_system_bindings (vertical_id, system, allowed_approaches, active)
VALUES
    ('people_hr', 'alumni_google_sheet', ARRAY['live', 'upload']::text[], true),
    ('bizdev', 'contact_us_google_sheet', ARRAY['live', 'upload']::text[], true)
ON CONFLICT (vertical_id, system) DO UPDATE
    SET allowed_approaches = EXCLUDED.allowed_approaches,
        active = EXCLUDED.active;

-- migrate:down
DELETE FROM vertical_system_bindings
 WHERE system IN ('alumni_google_sheet', 'contact_us_google_sheet');

ALTER TABLE vertical_system_bindings
    DROP CONSTRAINT IF EXISTS vertical_system_bindings_system_valid;

ALTER TABLE vertical_system_bindings
    ADD CONSTRAINT vertical_system_bindings_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni', 'axios_hq'
        ));

ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS integration_connections_system_valid;

ALTER TABLE integration_connections
    ADD CONSTRAINT integration_connections_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni', 'axios_hq'
        ));

ALTER TABLE vertical_hash_refresh_attempts
    DROP CONSTRAINT IF EXISTS vertical_hash_refresh_attempts_system_valid;

ALTER TABLE vertical_hash_refresh_attempts
    ADD CONSTRAINT vertical_hash_refresh_attempts_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets',
            'bizdev_contacts', 'hr_alumni', 'axios_hq'
        ));
