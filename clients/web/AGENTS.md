> inherits: ../../AGENTS.md

# AGENTS.md — clients/web/

Admin web single-page application.

## Locked stack

Vite · React · TypeScript · TanStack Router · TanStack Query · shadcn · Bun

## Realtime

Connect to admin-api `GET /live/events` (Server-Sent Events). Invalidate TanStack Query cache on `privacy_events` payloads.

## Navigation (Pipeline + Health)

- **Pipeline** hover menu → `/ops/drop-pipeline?tab=` (`home` | `download` | `ingest` | `matching` | `fulfillment`). Configurations is the home tab (hash-index enqueue / enqueue-all).
- **Health** click → `/ops/health` (workers + queues from admin_api). Hover → Escalations/retries (`/ops/health/escalations`) and Configuration (`/ops/health/configuration` — retry `max_attempts` via `/ops/health/retry-config`).
- Browser never calls worker URLs — only admin-api aggregates.

## DROP pipeline

- Tabbed process UX on `/ops/drop-pipeline` (query `tab=`).
- Ingest copy: **Unzip** (land) + **Promote to raw** (promote).
- Hash-index: per-state enqueue + enqueue-all served states (USPS 50+DC); rematch-on-refresh for every successful state.
- After **Run matching** completes (`status=ok`), required post-match dialog (review / bulk approve); `useBlocker` until choice.
- Matching results: stats, list ↔ detail (attempt history + allowlisted `audit_payload`), bulk approve by match type.

## Rules

- Thin client — no business rules in browser; all authorization on admin-api.
- Generate TypeScript types from admin-api OpenAPI.
- Not Next.js.
- No PII/hashes/dwids in UI payloads beyond existing ops id/count rules.

Full detail → [`.agent/modules/frontend-stack.md`](../../.agent/modules/frontend-stack.md).
