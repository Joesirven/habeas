# module: privacy-invariants

> Gate: code touching request, approval, attempt, or audit tables.

## Rules

- No personally identifiable information in application logs, structured log fields, or audit `arguments` / `error_payload`.
- Use `habeas_privacy_core.audit.redaction` helpers before persisting payloads.
- Append-only attempt tables — no update or delete on workflow history rows.
- `admin_audit_log`: revoke update/delete from application database role.
- Three audit layers (per knowledge base): attempt tables, admin audit log, PostgreSQL audit extension.

## When unsure

Stop and flag Jose — privacy regressions are not fix-forward in production.
