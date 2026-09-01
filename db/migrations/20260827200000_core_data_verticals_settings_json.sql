-- migrate:up
-- Per-vertical owner settings (notification toggles). Flags only — no PII.

ALTER TABLE data_verticals
    ADD COLUMN IF NOT EXISTS settings_json JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN data_verticals.settings_json IS
    'Owner-configured vertical settings (notify_email, notify_slack). Flags only — no PII.';

-- migrate:down
ALTER TABLE data_verticals DROP COLUMN IF EXISTS settings_json;
