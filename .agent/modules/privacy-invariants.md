# module: privacy-invariants

> Gate: code touching request, approval, attempt, or audit tables.

## Vocabulary

- **request** — one privacy request row; mutations go through admin-api only.
- **source** — intake origin. **CA DROP** is a source, not a catalog system or connection.
- **system** (connection) — a data system in a **vertical**. Matching review is **per system** (one owner verification per connection).
- **batch** — intake grouping (date + source), not a system.
- **data owner** configures connections; **data user** reviews and fulfills.
- **Test vertical** systems display as **System A** / **System B**. Other verticals use the real connection name.

## Rules

- No personally identifiable information in application logs, structured log fields, or audit `arguments` / `error_payload`.
- Use `habeas_privacy_core.audit.redaction` helpers before persisting payloads.
- Append-only attempt tables — no update or delete on workflow history rows.
- `admin_audit_log`: revoke update/delete from application database role.
- Three audit layers (per knowledge base): attempt tables, admin audit log, PostgreSQL audit extension.
- Integration connection secrets live in Secret Manager only — never echo tokens, API keys, or passwords in API responses, logs, or audit payloads. Owner connector access is vertical assignment + IAP login only — no invite or redeem URLs; all connection mutations go through admin-api.

## Fulfillment gates (request journey)

- Fulfillment for a vertical **must not** auto-start from data-owner `matching.review` alone — **Legal kickoff** gates start (CA DROP / delete-opt-out; optional `response_status` edit at/before kickoff).
- **Access** (and access leg of combined): identity **status + required comment** must clear before Access pack generation and Access notice templates. CA DROP has **no** identity gate and **cannot** be typed as Access.
- Combined non–CA DROP: delete/opt-out leg may proceed without identity; Access pack waits on identity-comment. Product contract: `docs/plans/2026-07-29-001-feat-request-journey-workbench-plan.md`.

## When unsure

Stop and flag Jose — privacy regressions are not fix-forward in production.
