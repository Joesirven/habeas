-- migrate:up
-- Thin spine (20260716000003) dropped requestor_state; DROP matching / rematch
-- (U20/U21) require it on requests for requester-source-state filtering.
ALTER TABLE requests
    ADD COLUMN IF NOT EXISTS requestor_state VARCHAR(2) NOT NULL DEFAULT 'CA';

ALTER TABLE requests
    DROP CONSTRAINT IF EXISTS requests_requestor_state_len;

ALTER TABLE requests
    ADD CONSTRAINT requests_requestor_state_len
        CHECK (char_length(requestor_state) = 2);

CREATE INDEX IF NOT EXISTS ix_requests_state_received
    ON requests (requestor_state, received_at);

COMMENT ON COLUMN requests.requestor_state IS
    'Normalized USPS state for BQ lookup + rematch-on-refresh scoping (U20/U21)';

-- migrate:down
DROP INDEX IF EXISTS ix_requests_state_received;

ALTER TABLE requests
    DROP CONSTRAINT IF EXISTS requests_requestor_state_len;

ALTER TABLE requests
    DROP COLUMN IF EXISTS requestor_state;
