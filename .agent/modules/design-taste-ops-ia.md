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
- Kind tabs (ops): All · Matching · Triage · Escalations · Delivery · Notice · Comms · Tasks.
- Kind tabs (Legal): Triage · Escalations · Notice · Delivery · Tasks — default Triage; no Matching/Comms/All. Fetch Legal lanes only (`getLegalNeedsAttention`) so matching volume cannot crowd the case queue. URL `?kind=`.
- Legal / data-owner persona: Home / My work (not pipeline Dashboard); hide Workers; Triage bulk Reject `2` / Send to matching; Escalations resolve via fulfill path + comments; Notice/Delivery empty until feeds wire; DO approve uses recommended `3`/`4`/`5`.
- Legal **Conditions** (`/requests/conditions`): version `intake.route_triage` via allowlist (`requestor_state_not_in`) or explicit Triage list (`state_in`); save closes active rule and inserts replacement.
- Legal **Notice**: fulfilled DROP rows (`response_status` set + `notice_review_status=pending`); bulk/detail **Approve notice**. **Delivery**: `communication_attempts` purpose `access_delivery` awaiting status (empty until access packs land).
- Queue rows: human title first, then source · lane · id, blocker/due — not id-first mono soup.
- Detail pane: title + meta strip, compact journey chips, focused Matching / Delivery / Notice body, comments footer.
- Delivery: shareable URL, Copy URL, **Draft outbound** (template with URL in body), delivery status.
- Under Matching: result-type chips (single / multi / not-found) — orthogonal to kind.
- Exact 1:1 matches from one DROP batch → expandable thread + bulk fulfill.
- Inbox **Fulfill** confirms CA DROP `response_status` (3 Deleted · 4 Opted out · 5 Not found) before approving `matching.review` — keep naming distinct from ingest **Promote-to-raw**.
- Checkbox list + bulk Fulfill/Decline; Select all covers every loaded row matching the active filters (not only the scrolled viewport); assign / comments in the right pane.

### Request detail / drawer

- Meta strip (source, received, stage, blocker).
- Tabs: History | Matching | Delivery.
- Delivery tab: same handoff + draft outbound template as Inbox.
- Matching must tolerate missing/legacy attempt payloads — never crash on empty audit JSON.

### Dashboard request processing pipeline

- Top console tabs: **Pipeline** · Hash refresh · History · Configurations (not Download/Ingest/Matching/Fulfillment at top).
- Header: **Run Pipeline** (shadcn dropdown → CA DROP + confirm dialog with staged queue). Compact metric cards with ring/spark viz + hover detail popovers.
- Pipeline list: shadcn Tabs (Bulk / Individual); compact Popover filters.
- Bulk cards: human title from `process_at`; collapsed ~1–2 lines with Dur/Prog inline + tiny stage chips (no Matching results in header); expanded title row shares Dur + Est/err; stage tabs Download · Ingest · Matching · **Review** · Fulfillment stay local (no URL write per click — apply `?stage=` once on expand).
- Matching completion % / Finished·Queued·Failed chips use `matching_attempts` only — never blend review (Review tab uses `detail.stages.review`).
- Stage strip: only **selected** tab is large (`emphasize = expanded && selected`; percent + progress); compact chips omit %; current-not-selected stays compact with an in-progress cue; Finished/Queued/Failed/Abandoned under selected; **Matching results** Inbox link when Review tab is selected.
- Expanded stage detail: compact state tiles + Stage dur / Bulk dur MiniRing chips (fulfillment tiles stay narrow); run-detail overview shows the same duration pair (`—` when bulk timestamps absent on the attempt payload).
- Bulk-card state tiles deep-link to `/ops/runs` with `process` (bulk download attempt id) + job + status + window — admin-api `GET /ops/runs?process_id=` scopes connector/ingest/matching via the download `gcs_uri`.
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
