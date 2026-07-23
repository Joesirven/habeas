# module: design-taste-ops-ia

> Gate: DROP Ops IA UI in `clients/web` — Runs, Requests, Inbox, Workers, Pipeline, request journey.

**Inherits:** [`design-taste.md`](design-taste.md) (shadcn + Habeas). This file only adds ops composition recipes.

## Composition recipes

### Requests list

- Filter toolbar (source, state, attention, raw, id, date range).
- Dense table; row opens request drawer; id link opens full page.

### Inbox (Needs attention)

- Dual-pane email layout: queue list (left) + review pane (right).
- Below `md`: show queue **or** detail (← Queue), never stack the pane under the list.
- Kind tabs: All · Matching · Delivery · Notice · Comms · Tasks.
- Queue rows: human title first, then source · lane · id, blocker/due — not id-first mono soup.
- Detail pane: title + meta strip, compact journey chips, focused Matching / Delivery / Notice body, comments footer.
- Delivery: shareable URL, Copy URL, **Draft outbound** (template with URL in body), delivery status.
- Under Matching: result-type chips (single / multi / not-found) — orthogonal to kind.
- Exact 1:1 matches from one DROP batch → expandable thread + bulk fulfill.
- Checkbox list + bulk Fulfill/Decline; Select all covers every loaded row matching the active filters (not only the scrolled viewport); assign / comments in the right pane.

### Request detail / drawer

- Meta strip (source, received, stage, blocker).
- Tabs: History | Matching | Delivery.
- Delivery tab: same handoff + draft outbound template as Inbox.
- Matching must tolerate missing/legacy attempt payloads — never crash on empty audit JSON.

### Dashboard request processing pipeline

- Top console tabs: **Pipeline** · Hash refresh · History · Configurations.
- Header: **Run Pipeline** (shadcn dropdown → CA DROP + confirm dialog with staged queue). Compact metric cards with ring/spark viz + hover detail popovers.
- Pipeline list: shadcn Tabs (Bulk / Individual); compact Popover filters.
- Bulk cards: ~1–2 line collapsed row — human `process_at` title, inline Dur/Prog, tiny stage chips; expanded keeps title + Dur + Est./error% on one row. Stage tabs (**Download · Ingest · Matching · Fulfillment**) stay local (no URL write per click — apply `?stage=` once on expand); only the **selected** tab is large when expanded; current-but-not-selected stays compact with an in-progress cue. **Matching results** only when the Matching stage is selected.
- Matching completion % / Finished·Queued·Failed chips use `matching_attempts` only — never blend review (review shares the request spine but doubles the denominator).
- Individual view: status toggles on the same filter row as Intake/Window (shared `RUN_STATUS_FILTERS` semantics with bulk-card toggles).
- Expanded runs: toggle filters, pagination, bulk Re-run / Assign / Details dialog → full Runs page.

### Workers

- Fleet table → click worker → full attempt history.
- Runs list links to `/ops/runs/{job}:{id}` detail.

### Run detail

- Overview metrics · Timeline · Output (error + JSON) · Events.

## Don’t

- Reintroduce Amigo frost, editorial heroes, or glass chips on ops routes.
- Duplicate Matching review as a top-level nav item.
