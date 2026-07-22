# module: design-taste-ops-ia

> Gate: DROP Ops IA UI in `clients/web` — Runs, Requests, Inbox, Workers, Pipeline, request journey.

**Inherits:** [`design-taste.md`](design-taste.md) (shadcn + Habeas). This file only adds ops composition recipes.

## Composition recipes

### Requests list

- Filter toolbar (source, state, attention, raw, id, date range).
- Dense table; row opens request drawer; id link opens full page.

### Inbox (Needs attention)

- Checkbox list + bulk Promote/Decline.
- Filter chips by source/stage.
- Row opens request drawer (matching review lives here).

### Request detail / drawer

- Meta strip (source, received, stage, blocker).
- Tabs: History | Matching.
- Matching must tolerate missing/legacy attempt payloads — never crash on empty audit JSON.

### Workers

- Fleet table → click worker → full attempt history.
- Runs list links to `/ops/runs/{job}:{id}` detail.

### Run detail

- Overview metrics · Timeline · Output (error + JSON) · Events.

## Don’t

- Reintroduce Amigo frost, editorial heroes, or glass chips on ops routes.
- Duplicate Matching review as a top-level nav item.
