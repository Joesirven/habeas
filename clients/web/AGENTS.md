> inherits: ../../AGENTS.md

# AGENTS.md — clients/web/

Admin web single-page application.

## Locked stack

Vite · React · TypeScript · TanStack Router · TanStack Query · shadcn · Bun

## Realtime

Connect to admin-api `GET /live/events` (Server-Sent Events). Invalidate TanStack Query cache on `privacy_events` payloads.

## Role-aware navigation (IA matrix)

Session: `GET /me` → `{ email, role }` via `getMe` / `useMeQuery` (`super_admin` | `admin` | `data_owner`). Probe `GET /auth/me` remains for splash identity only.

| Nav / route | Roles |
|-------------|--------|
| `/` Needs me | all |
| `/requests` | all |
| `/requests/needs-attention` (compat redirect from `/approvals/matching-review`) | all resolved ops roles |
| `/ops/insights` (thin) | all |
| `/ops/dashboard`, `/ops/runs`, `/ops/jobs`, `/ops/incidents`, `/ops/configuration` | `super_admin` |
| `/ops/drop-pipeline` (Pipeline) + `/ops/health/*` | `super_admin` |
| Splash lab (`/dev/splash-lab`) | DEV only |

`data_owner` / `admin`: no Runs, Pipeline, Jobs, Health, or ops Configuration power paths. Deep links to gated routes show a forbidden empty state (API 403 remains authoritative).

Ops chrome: `.agent/modules/design-taste-ops-ia.md` — micro eyebrow, compact title, `taste-panel` / table-first (not marketing heroes).

## Navigation (Pipeline + Health)

- **Pipeline** hover menu → `/ops/drop-pipeline?tab=` (`home` | `download` | `ingest` | `matching` | `fulfillment`). Configurations is the home tab (hash-index enqueue / enqueue-all).
- **Health** click → `/ops/health` (workers + queues from admin_api). Hover → Escalations/retries (`/ops/health/escalations`) and Configuration (`/ops/health/configuration` — retry `max_attempts` via `/ops/health/retry-config`).
- Browser never calls worker URLs — only admin-api aggregates.

## DROP pipeline

- Tabbed process UX on `/ops/drop-pipeline` (query `tab=`).
- Ingest copy: **Unzip** (land) + **Promote to raw** (promote).
- Hash-index: per-state enqueue + enqueue-all served states (USPS 50+DC); rematch-on-refresh for every successful state.
- After **Run matching** completes (`status=ok`), required post-match dialog (review / bulk approve); `useBlocker` until choice.
- Matching tab: stats, list ↔ detail (attempt history + allowlisted `audit_payload`),
  filters (request_id search, state select, recorded date range + match_type),
  promote/decline (individual + bulk by match type), assign to reviewer / escalate to
  legal|data_owner (IAP actor; `workflow.assignment` via admin-api).
  Approaching-SLA *aggregates* on Pipeline (`approaching_sla` from admin-api): age-policy
  counts of open work older than stage thresholds (matching 4h, review 48h, ingest 12h,
  connector 24h) — label as derived age policy, not legal breach clocks. List *filters*
  by deadline remain deferred (no deadline column).

## Rules

- Thin client — no business rules in browser; all authorization on admin-api.
- Generate TypeScript types from admin-api OpenAPI.
- Not Next.js.
- No PII/hashes/dwids in UI payloads beyond existing ops id/count rules.

Full detail → [`.agent/modules/frontend-stack.md`](../../.agent/modules/frontend-stack.md).
