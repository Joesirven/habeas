> inherits: ../AGENTS.md

# AGENTS.md — app/data_fulfillment_dispatcher/

**Kind:** automation

DROP fulfillment **stub**: after `matching.review` approval, set
`drop_raw_requests.response_status` from the latest `matching_results` row.
Does **not** call Tier-C suppression APIs (mailchimp, paylocity, etc.).

- `POST /fulfill` — one `request_id` or batch of ready DROP rows
- Gate: `is_matching_review_approved` — approved `matching.review` with
  `decided_at >=` latest `matching_results.recorded_at` (stale approvals after
  rematch do not unlock fulfill); same gate for statuses 3/4/5
- `match_count` 0 → `response_status=5` (Not found); 1 → `3` (Deleted); N>1 → `4` (Opted out)
- Rematch coherence (open + reopened Opted-out): fulfill always uses the
  **latest** `match_count`, so multi→1 / multi→0 cannot ship as stale Opted-out
  (4). After hash-index refresh, fulfilled `response_status=4` with latest
  match missing / 0 / >1 is rematched and **reopened** to NULL so fulfill can
  rewrite 3/4/5 from the new result (other fulfilled statuses 3/5 are not
  rematched).
- **No** fulfillment queue / attempts table — operates on `matching_results` +
  `drop_raw_requests` (reaper registry unchanged)

Schema in [`db/migrations/`](../../db/migrations/).
