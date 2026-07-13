-- migrate:up
CREATE TABLE approval_rules (
    id                  BIGSERIAL PRIMARY KEY,
    action_type         VARCHAR(50) NOT NULL,
    requires_approval   BOOLEAN NOT NULL DEFAULT false,
    approver_role       VARCHAR(30),
    condition_jsonb     JSONB,
    rationale           TEXT NOT NULL,
    effective_from      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_to        TIMESTAMPTZ,
    created_by          VARCHAR(200) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX ix_approval_rules_active
    ON approval_rules(action_type)
    WHERE effective_to IS NULL;

CREATE TABLE approval_requests (
    id                  BIGSERIAL PRIMARY KEY,
    request_id          UUID NOT NULL REFERENCES requests(id),
    action_type         VARCHAR(50) NOT NULL,
    rule_id             BIGINT REFERENCES approval_rules(id),
    approver_role       VARCHAR(30),
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',
    context_jsonb       JSONB,
    requested_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL,
    decided_by          VARCHAR(200),
    decided_at          TIMESTAMPTZ,
    decision_reason     TEXT,
    CONSTRAINT approval_requests_status_valid
        CHECK (status IN ('pending', 'approved', 'rejected', 'expired'))
);

CREATE INDEX ix_approval_requests_pending
    ON approval_requests (expires_at)
    WHERE status = 'pending';

CREATE INDEX ix_approval_requests_request
    ON approval_requests (request_id);

CREATE OR REPLACE FUNCTION core_notify_privacy_events()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_notify(
        'privacy_events',
        json_build_object(
            'table', TG_TABLE_NAME,
            'action', TG_OP,
            'id', NEW.id
        )::text
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER approval_requests_privacy_events
    AFTER INSERT OR UPDATE ON approval_requests
    FOR EACH ROW EXECUTE FUNCTION core_notify_privacy_events();

INSERT INTO approval_rules (
    action_type, requires_approval, approver_role, condition_jsonb, rationale, created_by
) VALUES
(
    'suppress.paylocity', true, 'data_owner.hr', NULL,
    'Paylocity contains payroll + employment records. Per legal policy 2026-05, all suppressions require explicit HR data owner review.',
    'lauren@habeas.com'
),
(
    'suppress.cassandra', false, NULL, NULL,
    'Cassandra restricted_person_id table is internal-only. Suppression is the canonical action; no human review adds value.',
    'jose@sirven.xyz'
),
(
    'suppress.mailchimp', false, NULL, NULL,
    'Mailchimp unsubscribe is the standard CCPA delete action; no review needed.',
    'jose@sirven.xyz'
),
(
    'match.override.low_confidence', true, 'compliance_lead', '{"confidence_lt": 0.85}',
    'Low-confidence matches risk suppressing the wrong person. Compliance lead must approve before downstream actions fire.',
    'sarah@habeas.com'
),
(
    'intake.out_of_jurisdiction', true, 'legal', '{"requestor_state_not_in": ["CA","CO","CT","UT","VA"]}',
    'States outside the current opt-out regulatory scope need legal review before processing.',
    'sarah@habeas.com'
);

CREATE TABLE core_workflow_test_attempts (
    id                  BIGSERIAL PRIMARY KEY,
    request_id          UUID NOT NULL REFERENCES requests(id),
    approval_id         BIGINT REFERENCES approval_requests(id),
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_code          VARCHAR(50),
    completed_at        TIMESTAMPTZ,
    CONSTRAINT core_workflow_test_attempts_status_valid
        CHECK (status IN ('pending', 'awaiting_approval', 'abandoned', 'success'))
);

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON approval_requests FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS core_workflow_test_attempts;
DROP TRIGGER IF EXISTS approval_requests_privacy_events ON approval_requests;
DROP FUNCTION IF EXISTS core_notify_privacy_events();
DROP TABLE IF EXISTS approval_requests;
DROP TABLE IF EXISTS approval_rules;
