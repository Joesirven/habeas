-- migrate:up
-- Communications vertical: axios_hq upload-only binding; mailchimp binding inactive (historical connections remain).

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

UPDATE vertical_system_bindings
   SET active = false
 WHERE vertical_id = 'communications'
   AND system = 'mailchimp';

INSERT INTO vertical_system_bindings (vertical_id, system, allowed_approaches, active)
VALUES ('communications', 'axios_hq', ARRAY['upload']::text[], true)
ON CONFLICT (vertical_id, system) DO UPDATE
    SET allowed_approaches = EXCLUDED.allowed_approaches,
        active = EXCLUDED.active;

-- migrate:down
DELETE FROM vertical_system_bindings
 WHERE vertical_id = 'communications'
   AND system = 'axios_hq';

UPDATE vertical_system_bindings
   SET active = true,
       allowed_approaches = ARRAY['live', 'upload']::text[]
 WHERE vertical_id = 'communications'
   AND system = 'mailchimp';

ALTER TABLE vertical_system_bindings
    DROP CONSTRAINT IF EXISTS vertical_system_bindings_system_valid;

ALTER TABLE vertical_system_bindings
    ADD CONSTRAINT vertical_system_bindings_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni'
        ));

ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS integration_connections_system_valid;

ALTER TABLE integration_connections
    ADD CONSTRAINT integration_connections_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni'
        ));

ALTER TABLE vertical_hash_refresh_attempts
    DROP CONSTRAINT IF EXISTS vertical_hash_refresh_attempts_system_valid;

ALTER TABLE vertical_hash_refresh_attempts
    ADD CONSTRAINT vertical_hash_refresh_attempts_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets',
            'bizdev_contacts', 'hr_alumni'
        ));
