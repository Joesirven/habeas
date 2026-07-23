> inherits: ../../AGENTS.md

# AGENTS.md — habeas-privacy-core/workflow/

Approval helpers, service level agreement computation, terminal error classification.

- Imported by apps and CLI — never import app code from here.
- No vendor-specific logic in this module.
- `is_matching_review_approved` requires approval after the latest
  `matching_results` row; `ensure_pending_matching_review` opens a fresh
  pending gate when rematch invalidates a prior approval.
- Match success opens the gate in the same DB transaction; reaper
  `/reap` calls `reconcile_ungated_matching_reviews` to backfill hangers.
- Assign/escalate (U17) stores pending `workflow.assignment` rows on
  `approval_requests` (append-history; supersede prior pending). Targets:
  `reviewer` | `legal` | `data_owner`. No separate assignment table.
