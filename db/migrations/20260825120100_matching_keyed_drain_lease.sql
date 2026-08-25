-- migrate:up
-- Expand singleton matching_drain_lease (id=1) to keyed leases so Data and
-- Auth0 drains can run in parallel. Keep id=1 on data-drop for expand-then-contract
-- (existing readers still WHERE id = 1).

ALTER TABLE matching_drain_lease
    ADD COLUMN IF NOT EXISTS lease_key TEXT;

UPDATE matching_drain_lease
   SET lease_key = 'data-drop'
 WHERE id = 1
   AND lease_key IS NULL;

ALTER TABLE matching_drain_lease
    DROP CONSTRAINT IF EXISTS matching_drain_lease_id_check;

ALTER TABLE matching_drain_lease
    DROP CONSTRAINT IF EXISTS matching_drain_lease_pkey;

ALTER TABLE matching_drain_lease
    ALTER COLUMN id DROP DEFAULT;

INSERT INTO matching_drain_lease (id, lease_key)
SELECT 1, 'data-drop'
 WHERE NOT EXISTS (
           SELECT 1
             FROM matching_drain_lease
            WHERE id = 1
               OR lease_key = 'data-drop'
       );

ALTER TABLE matching_drain_lease
    ALTER COLUMN lease_key SET NOT NULL;

ALTER TABLE matching_drain_lease
    ADD CONSTRAINT matching_drain_lease_pkey PRIMARY KEY (lease_key);

ALTER TABLE matching_drain_lease
    ADD CONSTRAINT matching_drain_lease_id_unique UNIQUE (id);

INSERT INTO matching_drain_lease (id, lease_key)
VALUES (2, 'auth0')
ON CONFLICT (lease_key) DO NOTHING;

COMMENT ON COLUMN matching_drain_lease.lease_key IS
    'Drain identity; data-drop is the former singleton id=1, auth0 is parallel.';

-- migrate:down
-- Safe restore to singleton id=1. Keep data-drop lease state; drop other keys.

DELETE FROM matching_drain_lease
 WHERE lease_key IS DISTINCT FROM 'data-drop';

INSERT INTO matching_drain_lease (id, lease_key, updated_at)
SELECT 1, 'data-drop', NOW()
 WHERE NOT EXISTS (SELECT 1 FROM matching_drain_lease);

UPDATE matching_drain_lease
   SET id = 1
 WHERE lease_key = 'data-drop'
   AND id IS DISTINCT FROM 1;

ALTER TABLE matching_drain_lease
    DROP CONSTRAINT IF EXISTS matching_drain_lease_id_unique;

ALTER TABLE matching_drain_lease
    DROP CONSTRAINT IF EXISTS matching_drain_lease_pkey;

ALTER TABLE matching_drain_lease
    DROP COLUMN IF EXISTS lease_key;

ALTER TABLE matching_drain_lease
    ALTER COLUMN id SET DEFAULT 1;

ALTER TABLE matching_drain_lease
    ALTER COLUMN id SET NOT NULL;

ALTER TABLE matching_drain_lease
    ADD CONSTRAINT matching_drain_lease_pkey PRIMARY KEY (id);

ALTER TABLE matching_drain_lease
    ADD CONSTRAINT matching_drain_lease_id_check CHECK (id = 1);
