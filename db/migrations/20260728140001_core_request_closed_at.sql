-- migrate:up
ALTER TABLE requests
  ADD COLUMN IF NOT EXISTS closed_at timestamptz,
  ADD COLUMN IF NOT EXISTS closed_by text;

CREATE INDEX IF NOT EXISTS idx_requests_closed_at
  ON requests (closed_at)
  WHERE closed_at IS NOT NULL;

-- migrate:down
DROP INDEX IF EXISTS idx_requests_closed_at;
ALTER TABLE requests
  DROP COLUMN IF EXISTS closed_by,
  DROP COLUMN IF EXISTS closed_at;
