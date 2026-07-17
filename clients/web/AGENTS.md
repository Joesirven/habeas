> inherits: ../../AGENTS.md

# AGENTS.md — clients/web/

Admin web single-page application.

## Locked stack

Vite · React · TypeScript · TanStack Router · TanStack Query · shadcn · Bun

## Realtime

Connect to admin-api `GET /live/events` (Server-Sent Events). Invalidate TanStack Query cache on `privacy_events` payloads.

## DROP ops (Unit 8 / 8b)

- Hash-index refresh lane on `/ops/drop` (enqueue / process).
- After **Run matching** completes (`status=ok`), a **required** post-match dialog forces a next action (review results or bulk approve) — not dismissible without a choice.
- Matching results panel: global stats, list ↔ detail, bulk approve by match type (`single_match` / `multi_match` status-4 / `not_found`) via admin-api.

## Rules

- Thin client — all authorization and business rules on admin-api.
- Generate TypeScript types from admin-api OpenAPI.
- Not Next.js.

Full detail → [`.agent/modules/frontend-stack.md`](../../.agent/modules/frontend-stack.md).
