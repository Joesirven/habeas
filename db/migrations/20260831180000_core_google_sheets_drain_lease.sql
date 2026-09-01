-- migrate:up
-- Seed matching_drain_lease for google_sheets Method E spine (id=6).
-- axios_headquarters/paylocity/lever leases live in 20260831170000.

INSERT INTO matching_drain_lease (id, lease_key)
VALUES (6, 'google_sheets')
ON CONFLICT (lease_key) DO NOTHING;

COMMENT ON COLUMN matching_drain_lease.lease_key IS
    'Drain identity; data-drop=id1, auth0=id2, axios_headquarters/paylocity/lever/google_sheets parallel.';

-- migrate:down

DELETE FROM matching_drain_lease
 WHERE lease_key = 'google_sheets';

COMMENT ON COLUMN matching_drain_lease.lease_key IS
    'Drain identity; data-drop=id1, auth0=id2, axios_headquarters/paylocity/lever parallel.';
