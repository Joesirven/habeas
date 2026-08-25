-- migrate:up
-- Auth0 vertical matching snapshots (request-scoped) + disposition vendor ids.
-- Privacy-safe: opaque vendor_record_id values only — no emails, hashes, or PII.

CREATE TABLE request_vertical_matching (
    id                              BIGSERIAL PRIMARY KEY,
    request_id                      UUID NOT NULL REFERENCES requests(id),
    vertical                        VARCHAR(50) NOT NULL,
    match_count                     INT NOT NULL,
    vendor_record_ids               JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_matching_attempt_id      BIGINT REFERENCES matching_attempts(id),
    recorded_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT request_vertical_matching_match_count_nonneg
        CHECK (match_count >= 0),
    CONSTRAINT request_vertical_matching_request_vertical_unique
        UNIQUE (request_id, vertical)
);

COMMENT ON TABLE request_vertical_matching IS
    'Per-request vertical match snapshot; opaque vendor_record_ids only — no PII/hashes.';

COMMENT ON COLUMN request_vertical_matching.vendor_record_ids IS
    'Opaque vendor record ids (e.g. Auth0 user_id); never emails, hashes, or names.';

CREATE INDEX ix_request_vertical_matching_request
    ON request_vertical_matching (request_id);

ALTER TABLE request_vertical_dispositions
    ADD COLUMN selected_vendor_record_ids JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN request_vertical_dispositions.selected_vendor_record_ids IS
    'Opaque vendor record ids confirmed on disposition; never emails, hashes, or names.';

-- migrate:down
ALTER TABLE request_vertical_dispositions
    DROP COLUMN IF EXISTS selected_vendor_record_ids;

DROP TABLE IF EXISTS request_vertical_matching;
