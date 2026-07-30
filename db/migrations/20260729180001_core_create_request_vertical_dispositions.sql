-- migrate:up
-- U1 / KTD3: per-vertical disposition is the durable source of record for the
-- gates that fulfillment reads. Live vertical today is 'data' (CA DROP hash);
-- coming-soon verticals get no rows until they go live.
-- status: 3 Deleted · 4 Opted out · 5 Not found (CPPA DROP response codes).

CREATE TABLE request_vertical_dispositions (
    id              BIGSERIAL PRIMARY KEY,
    request_id      UUID NOT NULL REFERENCES requests(id),
    vertical        VARCHAR(50) NOT NULL,
    status          SMALLINT NOT NULL,
    selected_dwids  JSONB NOT NULL DEFAULT '[]'::jsonb,
    decided_by      VARCHAR(200) NOT NULL,
    actor_role      VARCHAR(30),
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT request_vertical_dispositions_status_valid
        CHECK (status IN (3, 4, 5)),
    CONSTRAINT request_vertical_dispositions_request_vertical_unique
        UNIQUE (request_id, vertical)
);

CREATE INDEX ix_request_vertical_dispositions_request
    ON request_vertical_dispositions (request_id);

-- migrate:down
DROP TABLE IF EXISTS request_vertical_dispositions;
