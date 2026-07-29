-- migrate:up
ALTER TABLE requests
  ADD COLUMN IF NOT EXISTS due_at timestamptz,
  ADD COLUMN IF NOT EXISTS due_at_override_at timestamptz,
  ADD COLUMN IF NOT EXISTS due_at_override_by text;

CREATE TABLE IF NOT EXISTS legal_sla_settings (
  id int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  data_owner_review_days int NOT NULL DEFAULT 3,
  legal_pre_fulfillment_days int NOT NULL DEFAULT 2,
  fulfillment_days int NOT NULL DEFAULT 3,
  lifecycle_days int NOT NULL DEFAULT 6,
  drop_upload_day_of_week int NOT NULL DEFAULT 2,
  drop_upload_time_local text NOT NULL DEFAULT '00:00',
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by text
);

INSERT INTO legal_sla_settings (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS legal_team_members (
  email text PRIMARY KEY,
  active boolean NOT NULL DEFAULT true,
  added_at timestamptz NOT NULL DEFAULT now(),
  added_by text
);

CREATE INDEX IF NOT EXISTS idx_requests_due_at ON requests (due_at)
  WHERE due_at IS NOT NULL;

-- migrate:down
DROP INDEX IF EXISTS idx_requests_due_at;
DROP TABLE IF EXISTS legal_team_members;
DROP TABLE IF EXISTS legal_sla_settings;
ALTER TABLE requests
  DROP COLUMN IF EXISTS due_at_override_by,
  DROP COLUMN IF EXISTS due_at_override_at,
  DROP COLUMN IF EXISTS due_at;
