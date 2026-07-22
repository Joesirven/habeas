> inherits: ../../AGENTS.md

# AGENTS.md — clients/web/

Admin web single-page application.

## Locked stack

Vite · React · TypeScript · TanStack Router · TanStack Query · shadcn · Bun

## Realtime

Connect to admin-api `GET /live/events` (Server-Sent Events). Invalidate TanStack Query cache on `privacy_events` payloads.

## Navigation (Ops IA — Request / Job / Run)

- **Requests** → list (row opens journey), Needs attention, SLAs (shell).
- **Ops** (super_admin): Dashboard (stages + Hash refresh + Configurations), Workers, Runs, Jobs (shell), Insights (`/ops/health`), Incidents (shell → failed Runs).
- **Console** (super_admin): `/ops/drop-pipeline?tab=` mutation power surface.
- Browser never calls worker URLs — only admin-api aggregates.

## Ops density (Prefect / Dagster feel)

Keep Habeas Amigo/`taste-*` tokens (navy, frost chips, matte panels). On **Runs, Requests, Ops dashboard, request journey**:

- Table-first / rail-first composition — not landing-page heroes.
- Compact rows (`text-xs`, tight `py`), status tabs/filters, URL search params.
- Horizontal stage rail for request journey; dense run list like Dagster Runs.
- One volume strip/chart on ops dashboard (Prefect overview) — not four equal marketing KPI tiles as the whole page.
- Do **not** invent a second design system or copy Prefect dark/purple chrome.

Ops visual system: [`.agent/modules/design-taste-ops-ia.md`](../../.agent/modules/design-taste-ops-ia.md) (`habeas-ops-amigo-prefect-dagster`).  
General Amigo frost: [`.agent/modules/design-taste.md`](../../.agent/modules/design-taste.md).

## DROP pipeline

- Tabbed process UX on `/ops/drop-pipeline` (query `tab=`).
- Ingest copy: **Unzip** (land) + **Promote to raw** (promote).
- Hash-index: per-state enqueue + enqueue-all served states (USPS 50+DC); rematch-on-refresh for every successful state.
- After **Run matching** completes (`status=ok`), required post-match dialog (review / bulk approve); `useBlocker` until choice.
- Matching tab: stats, list ↔ detail (attempt history + allowlisted `audit_payload`),
  filters (request_id search, state select, recorded date range + match_type),
  promote/decline (individual + bulk by match type), assign to reviewer / escalate to
  legal|data_owner (IAP actor; `workflow.assignment` via admin-api).
  No deadline / approaching-SLA UI — requires schema not present.

## Rules

- Thin client — no business rules in browser; all authorization on admin-api.
- Generate TypeScript types from admin-api OpenAPI.
- Not Next.js.
- No PII/hashes/dwids in UI payloads beyond existing ops id/count rules.

Full detail → [`.agent/modules/frontend-stack.md`](../../.agent/modules/frontend-stack.md).
