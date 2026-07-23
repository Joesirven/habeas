-- migrate:up
-- Legal Command Center: route matching OOJ-style hits to Inbox · Triage.
-- Requires Legal action (bulk reject / review / send to matching) — never silent reject.
INSERT INTO approval_rules (
    action_type, requires_approval, approver_role, condition_jsonb, rationale, created_by
) VALUES
(
    'intake.route_triage', true, 'legal',
    '{"requestor_state_not_in": ["CA","CO","CT","UT","VA"]}',
    'States outside the current opt-out regulatory scope route to Legal Triage before matching.',
    'jose@sirven.xyz'
);

-- migrate:down
UPDATE approval_rules
   SET effective_to = NOW()
 WHERE action_type = 'intake.route_triage'
   AND effective_to IS NULL;
