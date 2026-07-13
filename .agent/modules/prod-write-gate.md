# module: prod-write-gate

> Gate: deploy to production, production migration, Habeas CLI `--execute`, or any Cloud Run config change affecting prod.

## Rules

- **Stop and ask Jose** before prod writes, prod migrations, or first deploy of a new app.
- Mutations go through `app/admin_api` only — audited in `admin_audit_log`.
- Command-line writes use `--execute`; without it, show dry-run only.
- No force push to `master`.

## After approval

- Cloud Build deploys per-app; run `dbmate up` before new revision serves traffic.
- Verify audit row created for each human or agent mutation.
