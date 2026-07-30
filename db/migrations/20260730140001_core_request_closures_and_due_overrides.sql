-- migrate:up
-- Move close + due override off the immutable requests spine (ADR-08 / ADR-33).

CREATE TABLE IF NOT EXISTS request_closures (
    id              BIGSERIAL PRIMARY KEY,
    request_id      UUID NOT NULL REFERENCES requests(id),
    closed_by       TEXT NOT NULL,
    closed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT request_closures_request_unique UNIQUE (request_id)
);

CREATE INDEX IF NOT EXISTS ix_request_closures_closed_at
    ON request_closures (closed_at);

COMMENT ON TABLE request_closures IS
    'Append-only close facts; open request = no row for request_id.';

CREATE TABLE IF NOT EXISTS request_due_overrides (
    id              BIGSERIAL PRIMARY KEY,
    request_id      UUID NOT NULL REFERENCES requests(id),
    due_at          TIMESTAMPTZ NOT NULL,
    overridden_by   TEXT NOT NULL,
    overridden_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_request_due_overrides_request
    ON request_due_overrides (request_id, overridden_at DESC);

COMMENT ON TABLE request_due_overrides IS
    'Append-only admin deadline overrides; current due = COALESCE(latest, calculated).';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'requests'
           AND column_name = 'closed_at'
    ) THEN
        INSERT INTO request_closures (request_id, closed_by, closed_at)
        SELECT id,
               COALESCE(closed_by, 'migration:unknown'),
               closed_at
          FROM requests
         WHERE closed_at IS NOT NULL
        ON CONFLICT (request_id) DO NOTHING;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'requests'
           AND column_name = 'due_at_override_at'
    ) THEN
        INSERT INTO request_due_overrides (request_id, due_at, overridden_by, overridden_at)
        SELECT id,
               due_at,
               COALESCE(due_at_override_by, 'migration:unknown'),
               due_at_override_at
          FROM requests
         WHERE due_at_override_at IS NOT NULL
           AND due_at IS NOT NULL;
    END IF;
END $$;

DROP INDEX IF EXISTS idx_requests_due_at;
DROP INDEX IF EXISTS idx_requests_closed_at;

ALTER TABLE requests
    DROP COLUMN IF EXISTS due_at_override_by,
    DROP COLUMN IF EXISTS due_at_override_at,
    DROP COLUMN IF EXISTS due_at,
    DROP COLUMN IF EXISTS closed_by,
    DROP COLUMN IF EXISTS closed_at;

CREATE OR REPLACE FUNCTION core_forbid_requests_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'requests rows are immutable (id=%)', OLD.id;
END;
$$;

DROP TRIGGER IF EXISTS requests_forbid_mutation ON requests;
CREATE TRIGGER requests_forbid_mutation
    BEFORE UPDATE OR DELETE ON requests
    FOR EACH ROW EXECUTE FUNCTION core_forbid_requests_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON requests FROM app_user;
        REVOKE UPDATE, DELETE ON request_closures FROM app_user;
        REVOKE UPDATE, DELETE ON request_due_overrides FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS requests_forbid_mutation ON requests;
DROP FUNCTION IF EXISTS core_forbid_requests_mutation();

ALTER TABLE requests
    ADD COLUMN IF NOT EXISTS due_at timestamptz,
    ADD COLUMN IF NOT EXISTS due_at_override_at timestamptz,
    ADD COLUMN IF NOT EXISTS due_at_override_by text,
    ADD COLUMN IF NOT EXISTS closed_at timestamptz,
    ADD COLUMN IF NOT EXISTS closed_by text;

UPDATE requests AS r
   SET closed_at = c.closed_at,
       closed_by = c.closed_by
  FROM request_closures c
 WHERE c.request_id = r.id;

UPDATE requests AS r
   SET due_at = o.due_at,
       due_at_override_at = o.overridden_at,
       due_at_override_by = o.overridden_by
  FROM (
      SELECT DISTINCT ON (request_id)
             request_id, due_at, overridden_at, overridden_by
        FROM request_due_overrides
       ORDER BY request_id, overridden_at DESC
  ) o
 WHERE o.request_id = r.id;

CREATE INDEX IF NOT EXISTS idx_requests_due_at ON requests (due_at)
  WHERE due_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_requests_closed_at ON requests (closed_at)
  WHERE closed_at IS NOT NULL;

DROP TABLE IF EXISTS request_due_overrides;
DROP TABLE IF EXISTS request_closures;
