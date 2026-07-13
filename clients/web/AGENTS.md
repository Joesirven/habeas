> inherits: ../../AGENTS.md

# AGENTS.md — clients/web/

Admin web single-page application.

## Locked stack

Vite · React · TypeScript · TanStack Router · TanStack Query · shadcn · Bun

## Realtime

Connect to admin-api `GET /live/events` (Server-Sent Events). Invalidate TanStack Query cache on `privacy_events` payloads.

## Rules

- Thin client — all authorization and business rules on admin-api.
- Generate TypeScript types from admin-api OpenAPI.
- Not Next.js.

Full detail → [`.agent/modules/frontend-stack.md`](../../.agent/modules/frontend-stack.md).
