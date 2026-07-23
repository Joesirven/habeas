-- migrate:up
-- Single-flight orchestration lease for matching chunk drain Jobs (not work rows).
CREATE TABLE matching_drain_lease (
    id              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    holder          VARCHAR(100),
    acquired_at     TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO matching_drain_lease (id) VALUES (1);

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, UPDATE ON matching_drain_lease TO app_user;
    END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS matching_drain_lease;
