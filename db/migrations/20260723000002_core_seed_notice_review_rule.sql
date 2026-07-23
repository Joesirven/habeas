-- migrate:up
-- Legal Inbox · Notice: fulfilled DROP rows need notice.review before Wed upload.
INSERT INTO approval_rules (
    action_type, requires_approval, approver_role, condition_jsonb, rationale, created_by
) VALUES
(
    'notice.review', true, 'legal', NULL,
    'Fulfilled DROP requests require Legal notice.review before weekly response upload.',
    'jose@sirven.xyz'
);

-- migrate:down
UPDATE approval_rules
   SET effective_to = NOW()
 WHERE action_type = 'notice.review'
   AND effective_to IS NULL;
