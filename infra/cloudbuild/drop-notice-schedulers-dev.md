# DROP notice upload / amend Cloud Scheduler (dev)

Timezone: **America/Los_Angeles**

| Job | Cron | Target |
|-----|------|--------|
| Weekly upload | `0 0 * * 3` (Wed 00:00) | `POST {DROP_NOTICE_DISPATCHER_URL}/upload-weekly` |
| Weekly amend | `0 4 * * 3` (Wed 04:00) | `POST {DROP_NOTICE_DISPATCHER_URL}/amend-weekly` |

Amend eligibility: `drop_response_submission_ids` last status ≠ current `response_status` (hash-index refresh rematch).

Wire OIDC / Cloud Run invoker the same way as other worker schedulers in this repo. Sandbox host guard remains in `drop_connector` (`DROP_ENV=sandbox`).
