-- migrate:up
INSERT INTO approval_rules (
    action_type, requires_approval, approver_role, condition_jsonb, rationale, created_by
) VALUES
(
    'notice.review', true, 'compliance_lead', NULL,
    'MVP: all fulfilled DROP requests require human notice.review before weekly response upload (U10).',
    'jose@sirven.xyz'
);

-- migrate:down
UPDATE approval_rules
   SET effective_to = NOW()
 WHERE action_type = 'notice.review'
   AND effective_to IS NULL;
