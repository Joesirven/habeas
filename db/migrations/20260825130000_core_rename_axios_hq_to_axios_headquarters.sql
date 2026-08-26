-- migrate:up
-- Expand catalog CHECKs to include axios_headquarters (KB slug) and rewrite
-- axios_hq rows. Historical mailchimp remains in CHECK (connections may still exist).

ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS integration_connections_system_valid;

UPDATE integration_connections
    SET system = 'axios_headquarters'
    WHERE system = 'axios_hq';

ALTER TABLE integration_connections
    ADD CONSTRAINT integration_connections_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni', 'axios_headquarters',
            'alumni_google_sheet', 'contact_us_google_sheet'
        ));

ALTER TABLE vertical_system_bindings
    DROP CONSTRAINT IF EXISTS vertical_system_bindings_system_valid;

UPDATE vertical_system_bindings
    SET system = 'axios_headquarters'
    WHERE system = 'axios_hq';

ALTER TABLE vertical_system_bindings
    ADD CONSTRAINT vertical_system_bindings_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni', 'axios_headquarters',
            'alumni_google_sheet', 'contact_us_google_sheet'
        ));

DO $$
BEGIN
    IF to_regclass('public.vertical_hash_refresh_attempts') IS NULL THEN
        RETURN;
    END IF;

    ALTER TABLE vertical_hash_refresh_attempts
        DROP CONSTRAINT IF EXISTS vertical_hash_refresh_attempts_system_valid;

    UPDATE vertical_hash_refresh_attempts
        SET system = 'axios_headquarters'
        WHERE system = 'axios_hq';

    ALTER TABLE vertical_hash_refresh_attempts
        ADD CONSTRAINT vertical_hash_refresh_attempts_system_valid
            CHECK (system IN (
                'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets',
                'bizdev_contacts', 'hr_alumni', 'axios_headquarters',
                'alumni_google_sheet', 'contact_us_google_sheet'
            ));
END $$;

-- migrate:down
ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS integration_connections_system_valid;

UPDATE integration_connections
    SET system = 'axios_hq'
    WHERE system = 'axios_headquarters';

ALTER TABLE integration_connections
    ADD CONSTRAINT integration_connections_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni', 'axios_hq',
            'alumni_google_sheet', 'contact_us_google_sheet'
        ));

ALTER TABLE vertical_system_bindings
    DROP CONSTRAINT IF EXISTS vertical_system_bindings_system_valid;

UPDATE vertical_system_bindings
    SET system = 'axios_hq'
    WHERE system = 'axios_headquarters';

ALTER TABLE vertical_system_bindings
    ADD CONSTRAINT vertical_system_bindings_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni', 'axios_hq',
            'alumni_google_sheet', 'contact_us_google_sheet'
        ));

DO $$
BEGIN
    IF to_regclass('public.vertical_hash_refresh_attempts') IS NULL THEN
        RETURN;
    END IF;

    ALTER TABLE vertical_hash_refresh_attempts
        DROP CONSTRAINT IF EXISTS vertical_hash_refresh_attempts_system_valid;

    UPDATE vertical_hash_refresh_attempts
        SET system = 'axios_hq'
        WHERE system = 'axios_headquarters';

    ALTER TABLE vertical_hash_refresh_attempts
        ADD CONSTRAINT vertical_hash_refresh_attempts_system_valid
            CHECK (system IN (
                'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets',
                'bizdev_contacts', 'hr_alumni', 'axios_hq',
                'alumni_google_sheet', 'contact_us_google_sheet'
            ));
END $$;
