# module: frontend-stack

> Gate: editing `clients/web/`.

## Locked stack

| Piece | Choice |
|-------|--------|
| Build | Vite |
| UI | React, TypeScript, Tailwind, shadcn/ui |
| Package manager | Bun |
| Routing | **TanStack Router** |
| Server state | **TanStack Query** |
| Live updates | **Server-Sent Events** — `GET /live/events` on admin-api |
| Types | Generate from admin-api OpenAPI schema |

## Realtime flow (v0)

1. Postgres `NOTIFY privacy_events` on **approval_requests** changes (and related tables as needed).
2. admin-api `LISTEN privacy_events` → forwards to Server-Sent Events clients.
3. Web `EventSource` → TanStack Query `invalidateQueries` for affected resources.

## Rules

- Thin client — no business rules in browser; all authorization on admin-api.
- Not Next.js — single-page app on Firebase Hosting behind Identity-Aware Proxy.
- Mutations never bypass admin-api.
