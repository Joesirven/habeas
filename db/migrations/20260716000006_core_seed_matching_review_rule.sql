-- migrate:up
INSERT INTO approval_rules (
    action_type, requires_approval, approver_role, condition_jsonb, rationale, created_by
) VALUES
(
    'matching.review', true, 'compliance_lead', NULL,
    'MVP: all DROP matches require human matching.review before fulfillment dispatch (ADR-36 / Q2).',
    'jose@sirven.xyz'
);

-- migrate:down
UPDATE approval_rules
   SET effective_to = NOW()
 WHERE action_type = 'matching.review'
   AND effective_to IS NULL;
