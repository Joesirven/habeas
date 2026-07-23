-- migrate:up
-- Access handoff ledger statuses (shareable URL + delivery status; no mailer).
ALTER TABLE communication_attempts
    DROP CONSTRAINT IF EXISTS communication_attempts_status_valid;

ALTER TABLE communication_attempts
    ADD CONSTRAINT communication_attempts_status_valid
        CHECK (status IN (
            'recorded', 'pending', 'sent', 'failed', 'delivered', 'recalled'
        ));

-- migrate:down
ALTER TABLE communication_attempts
    DROP CONSTRAINT IF EXISTS communication_attempts_status_valid;

ALTER TABLE communication_attempts
    ADD CONSTRAINT communication_attempts_status_valid
        CHECK (status IN ('recorded', 'pending', 'sent', 'failed'));
