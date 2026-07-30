-- migrate:up
-- HR recruiting (Lever) suppressions require data-owner review, same posture as Paylocity.
INSERT INTO approval_rules (
    action_type, requires_approval, approver_role, condition_jsonb, rationale, created_by
) VALUES
(
    'suppress.lever', true, 'data_owner.hr', NULL,
    'Lever holds candidate recruiting records. Suppressions require explicit HR data owner review.',
    'jose@sirven.xyz'
);

-- migrate:down
DELETE FROM approval_rules WHERE action_type = 'suppress.lever';
