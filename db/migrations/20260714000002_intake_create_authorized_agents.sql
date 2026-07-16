-- migrate:up
CREATE TABLE authorized_agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100) NOT NULL,
    drive_folder_id VARCHAR(200),
    adapter_key     VARCHAR(50) NOT NULL,
    column_mapping  JSONB NOT NULL DEFAULT '{}'::jsonb,
    active          BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX ux_authorized_agents_adapter_key
    ON authorized_agents (adapter_key);

-- migrate:down
DROP TABLE IF EXISTS authorized_agents;
