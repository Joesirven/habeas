-- migrate:up
-- Retire mailchimp from catalog CHECKs (code stop only) and seed parallel drain
-- leases for axios_headquarters / paylocity / lever (Auth0-style Method E spines).
--
-- Do NOT DELETE mailchimp_attempts rows here — table purge is Jose-gated.
-- Historical integration_connections / vertical_hash_refresh_attempts with
-- system='mailchimp' may still exist; new CHECKs are added NOT VALID so existing
-- rows remain readable while new inserts cannot use mailchimp.

-- Parallel drain leases (ids 3–5; data-drop=1, auth0=2 from keyed-lease migration).
INSERT INTO matching_drain_lease (id, lease_key)
VALUES
    (3, 'axios_headquarters'),
    (4, 'paylocity'),
    (5, 'lever')
ON CONFLICT (lease_key) DO NOTHING;

COMMENT ON COLUMN matching_drain_lease.lease_key IS
    'Drain identity; data-drop=id1, auth0=id2, axios_headquarters/paylocity/lever parallel.';

-- Drop inactive mailchimp binding so vertical_system_bindings CHECK can exclude it.
DELETE FROM vertical_system_bindings
 WHERE system = 'mailchimp';

ALTER TABLE vertical_system_bindings
    DROP CONSTRAINT IF EXISTS vertical_system_bindings_system_valid;

ALTER TABLE vertical_system_bindings
    ADD CONSTRAINT vertical_system_bindings_system_valid
        CHECK (system IN (
            'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni', 'axios_headquarters',
            'alumni_google_sheet', 'contact_us_google_sheet'
        ));

ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS integration_connections_system_valid;

ALTER TABLE integration_connections
    ADD CONSTRAINT integration_connections_system_valid
        CHECK (system IN (
            'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni', 'axios_headquarters',
            'alumni_google_sheet', 'contact_us_google_sheet'
        )) NOT VALID;

DO $$
BEGIN
    IF to_regclass('public.vertical_hash_refresh_attempts') IS NULL THEN
        RETURN;
    END IF;

    ALTER TABLE vertical_hash_refresh_attempts
        DROP CONSTRAINT IF EXISTS vertical_hash_refresh_attempts_system_valid;

    ALTER TABLE vertical_hash_refresh_attempts
        ADD CONSTRAINT vertical_hash_refresh_attempts_system_valid
            CHECK (system IN (
                'paylocity', 'lever', 'auth0', 'google_sheets',
                'bizdev_contacts', 'hr_alumni', 'axios_headquarters',
                'alumni_google_sheet', 'contact_us_google_sheet'
            )) NOT VALID;
END $$;

-- migrate:down
-- Restore mailchimp in catalog CHECKs and communications binding; drop new leases.

DELETE FROM matching_drain_lease
 WHERE lease_key IN ('axios_headquarters', 'paylocity', 'lever');

COMMENT ON COLUMN matching_drain_lease.lease_key IS
    'Drain identity; data-drop is the former singleton id=1, auth0 is parallel.';

ALTER TABLE vertical_system_bindings
    DROP CONSTRAINT IF EXISTS vertical_system_bindings_system_valid;

ALTER TABLE vertical_system_bindings
    ADD CONSTRAINT vertical_system_bindings_system_valid
        CHECK (system IN (
            'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets', 'cassandra',
            'bizdev_contacts', 'hr_alumni', 'axios_headquarters',
            'alumni_google_sheet', 'contact_us_google_sheet'
        ));

INSERT INTO vertical_system_bindings (vertical_id, system, allowed_approaches, active)
VALUES ('communications', 'mailchimp', ARRAY['live', 'upload']::text[], false)
ON CONFLICT (vertical_id, system) DO UPDATE
    SET allowed_approaches = EXCLUDED.allowed_approaches,
        active = EXCLUDED.active;

ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS integration_connections_system_valid;

ALTER TABLE integration_connections
    ADD CONSTRAINT integration_connections_system_valid
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

    ALTER TABLE vertical_hash_refresh_attempts
        ADD CONSTRAINT vertical_hash_refresh_attempts_system_valid
            CHECK (system IN (
                'mailchimp', 'paylocity', 'lever', 'auth0', 'google_sheets',
                'bizdev_contacts', 'hr_alumni', 'axios_headquarters',
                'alumni_google_sheet', 'contact_us_google_sheet'
            ));
END $$;
