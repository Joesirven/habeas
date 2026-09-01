> inherits: ../AGENTS.md

# AGENTS.md — app/data_fulfillment_dispatcher/

**Kind:** automation

After `matching.review` approval, fulfill by `request_type`:

- **delete / opt_out (DROP):** enqueue `data_fulfillment_attempts` step
  `suppression`, write pipe-delimited DWID file under
  `bulk-run/{process_id}/suppression/dwids.txt` when
  `FULFILLMENT_GCS_BUCKET` is set, set `drop_raw_requests.response_status`
  (0→5, 1→3, N>1→4), open pending `notice.review`.
- **access:** enqueue step `reproduction`, export BQ allowlist tables to
  `bulk-run/{process_id}/request/{request_id}/` + `manifest.json`, record
  `communication_attempts` purpose `access_delivery` status `pending`
  (operator copies shareable URL outside the platform — no mailer).

Does **not** call Tier-C suppression APIs (paylocity, axios headquarters, etc.).

- `POST /fulfill` — one `request_id` or batch of ready rows
- Gate: `is_matching_review_approved`
- Queue table: `data_fulfillment_attempts` (reaper-registered)
- Rematch: latest `match_count` wins; GCS failure must not set `response_status`

Schema in [`db/migrations/`](../../db/migrations/).
