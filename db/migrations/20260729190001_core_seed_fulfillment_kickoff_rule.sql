-- migrate:up
-- U2 / KTD4: Legal kickoff gates fulfillment per vertical. Data-owner
-- matching.review alone must never start suppression or access packs (R11).
-- The approved vertical is carried in approval_requests.context_jsonb->>'vertical'.
-- NULL condition_jsonb: kickoff is always required, no predicate escape hatch.
-- Guarded insert so re-running after the soft-close below cannot collide with
-- ix_approval_rules_active (unique action_type while effective_to IS NULL).
INSERT INTO approval_rules (
    action_type, requires_approval, approver_role, condition_jsonb, rationale, created_by
)
SELECT 'fulfillment.kickoff', true, 'legal', NULL,
       'Fulfillment for a vertical requires Legal kickoff after disposition.',
       'jose@sirven.xyz'
 WHERE NOT EXISTS (
         SELECT 1
           FROM approval_rules
          WHERE action_type = 'fulfillment.kickoff'
            AND effective_to IS NULL
       );

-- migrate:down
-- Soft close: approval_rules is versioned history, so the seeded row is retired
-- rather than deleted — approved kickoffs keep pointing at their rule_id.
UPDATE approval_rules
   SET effective_to = NOW()
 WHERE action_type = 'fulfillment.kickoff'
   AND effective_to IS NULL;
