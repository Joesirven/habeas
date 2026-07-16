> inherits: ../AGENTS.md

# AGENTS.md — app/data_fulfillment_dispatcher/

**Kind:** automation

DROP fulfillment **stub**: after `matching.review` approval, set
`drop_raw_requests.response_status` from the latest `matching_results` row.
Does **not** call Tier-C suppression APIs (mailchimp, paylocity, etc.).

- `POST /fulfill` — one `request_id` or batch of ready DROP rows
- Gate: `is_matching_review_approved` (`matching.review` approved)
- Match → `response_status=3` (Deleted); no-match → `5` (Not found)
- **No** fulfillment queue / attempts table — operates on `matching_results` +
  `drop_raw_requests` (reaper registry unchanged)

Schema in [`db/migrations/`](../../db/migrations/).
