# module: design-taste-ops-ia

> Gate: DROP Ops IA UI in `clients/web` — Runs, Requests, Inbox, Workers, Pipeline, request journey.

**Inherits:** [`design-taste.md`](design-taste.md) (shadcn + Habeas). This file only adds ops composition recipes.

## Vocabulary

- **request** — one privacy request.
- **source** — intake origin. **CA DROP** is a source (also access portal / authorized agent / manual). Never a connection.
- **system** (connection) — a data system in a vertical. Owner verifies matching **per system** (separate matching-review rows).
- **vertical** — org slice that owns systems. **Test vertical** systems display as **System A** / **System B**; other verticals use the real connection name.
- **batch** — date + source grouping (e.g. `Aug 21 · CA DROP`).
- **matching-review item** — one review row for a request in one system.
- **data owner** / **data user** — owner configures connections; user reviews and fulfills.

Source filter = DROP vs other intake. System filter = catalog connections (Alumni, Mailchimp, …). Do not put CA DROP next to Alumni as a system chip.

## Composition recipes

### Requests list

- Filter toolbar (source, state, attention, raw, id, date range).
- Dense table; row opens request drawer; id link opens full page.

### Inbox (Needs attention)

- Dual-pane email layout: queue list (left) + review pane (right).
- Below `md`: show queue **or** detail (← Queue), never stack the pane under the list.
- Kind tabs (ops): All · Matching · Triage · Escalations · Delivery · Notice · Comms · Tasks.
- Kind tabs (Legal): Triage · Escalations · Notice · Delivery · Tasks — default Triage; no Matching/Comms/All. Fetch Legal lanes only (`getLegalNeedsAttention`) so matching volume cannot crowd the case queue. URL `?kind=`.
- Legal / data-owner persona: Home / My work (not pipeline Dashboard); hide Workers; Triage bulk Reject `2` / Send to matching; Escalations resolve via fulfill path + comments; DO approve uses recommended `3`/`4`/`5`. DO **Tasks** = `assignee=me` (My work Assigned card → `?kind=pending_tasks`).
- Legal **Conditions** (`/requests/conditions`): version `intake.route_triage` via allowlist (`requestor_state_not_in`) or explicit Triage list (`state_in`); save closes active rule and inserts replacement.
- Legal **Notice**: fulfilled DROP rows (`response_status` set + `notice_review_status=pending`); bulk/detail **Approve notice**. **Delivery**: `communication_attempts` purpose `access_delivery` awaiting status; Legal **Mark delivered / failed / recalled** via `PATCH …/workflow/delivery/{id}/status` (shareable URL when access packs land).
- Queue rows: human title first, then source · lane · id, blocker/due — not id-first mono soup. **No journey strip on list rows** — chrome lives on opened detail only. No `#N loaded (of M) · K groups` status in the Inbox / Results lab top bar.
- **Source** vs **system**: source is intake (CA DROP). System chips and Group-by System are catalog connections only. Test vertical chips read System A / System B. Owner inbox = one matching-review row per system.
- Detail pane (opened request): title + meta strip, **four-panel journey workbench** (Ingest · Matching · Fulfillment · Notice), focused Matching / Delivery / Notice body, comments footer. Product contract: `docs/plans/2026-07-29-001-feat-request-journey-workbench-plan.md`.
- **Batch selection** in the review pane shows the **same workbench with aggregate** Matching/Fulfillment vertical posture (not a thin chip strip).
- Delivery: shareable URL, Copy URL, **Draft outbound** (template with URL in body), delivery status.
- Under Matching: result-type chips (single / multi / not-found) — orthogonal to kind.
- Exact 1:1 matches from one DROP batch → expandable thread + bulk fulfill.
- Inbox **Fulfill** / data-owner disposition confirms CA DROP `response_status` (3 Deleted · 4 Opted out · 5 Not found) before approving `matching.review` — keep naming distinct from ingest **Promote-to-raw**. **Legal kickoff** (not matching approve alone) starts Fulfillment; **Access** requires identity status + required comment before pack/notice.
- Checkbox list + bulk Fulfill/Decline; Select all covers every loaded row matching the active filters (not only the scrolled viewport); assign / comments in the right pane.

### Request journey workbench (detail-only)

- High-level rail on **opened batch detail** and **individual request detail** only: **Ingest → Matching → Fulfillment → Notice**. Never on Inbox/All-requests list rows.
- Matching and Fulfillment are **separate per-vertical clusters** (indicator, progress, short status). Live verticals are `data`, `auth0`, `communications` (Axios HQ / `axios_hq`), and `people_hr` (Lever / Paylocity). Catalog-only (`cassandra`, `bizdev`) are greyed and non-actionable — workbench chrome is “catalog-only — matching is not live.” Mailchimp is retired. Split in-progress when any vertical is still Matching and any has started Fulfillment.
- Substeps vary by request type / intake (CA DROP vs Access vs combined vs delete/opt-out).
- Do not reintroduce six-label coarse rails (receive → … → delivery) as the primary detail chrome — those nest under the four stages.

### Request detail / drawer

- Meta strip (source, received, stage, blocker) + four-stage journey workbench (above).
- Tabs: History | Matching | Delivery (Fulfillment default for legal/admin pre-fulfillment).
- Delivery tab: same handoff + draft outbound template as Inbox.
- Matching must tolerate missing/legacy attempt payloads — never crash on empty audit JSON.

### Dashboard request processing pipeline

- Top console tabs: **Pipeline** · Hash refresh · History · Errors · Logs (not Download/Ingest/Matching/Fulfillment at top; no Configurations tab).
- Errors / Logs: shared GCP-style log explorer over attempt tables + admin audit (`severity=ERROR` vs all). ERROR severity is applied in SQL so sparse failures are not crowded out by INFO volume.
- Header: **Run Pipeline** (shadcn dropdown → CA DROP + confirm dialog with staged queue; dialog stays viewport-`fixed`) + gear → Workers Settings.
- Schedules, retry floors, fleet discovery: **Workers → Settings** only (`/ops/workers/settings`).
- Pipeline list: shadcn Tabs (Bulk / Individual); compact Popover filters.
- Bulk cards: human title from `process_at`; collapsed ~1–2 lines with Dur/Prog inline + tiny stage chips (no Matching results in header); expanded title row shares Dur + Est/err; stage tabs Download · Ingest · Matching · **Review** · Fulfillment stay local (no URL write per click — apply `?stage=` once on expand).
- Matching completion % / Finished·Queued·Failed chips use `matching_attempts` only — never blend review (Review tab uses `detail.stages.review`).
- Stage strip: only **selected** tab is large (`emphasize = expanded && selected`; percent + progress); compact chips omit %; current-not-selected stays compact with an in-progress cue; Finished/Queued/Failed/Abandoned under selected; **Matching results** Inbox link when Review tab is selected.
- Expanded stage detail: compact state tiles + Stage dur / Bulk dur MiniRing chips (fulfillment tiles stay narrow); run-detail overview shows the same duration pair (`—` when bulk timestamps absent on the attempt payload).
- Bulk-card state tiles deep-link to `/ops/runs` with `process` (bulk download attempt id) + job + status + window — admin-api `GET /ops/runs?process_id=` scopes connector/ingest/matching via the download `gcs_uri`.
- Individual view: status toggles on the same filter row as Intake/Window (shared `RUN_STATUS_FILTERS` semantics with bulk-card toggles).
- Expanded runs: toggle filters, pagination, bulk Re-run / Assign / Details dialog → full Runs page.

### Workers

- Fleet table from Scheduler ∪ Cloud Run discovery (`GET /ops/workers/fleet`) → click worker → attempt history / queue browser.
- Settings: schedules + retry + attempt-table index (no per-worker UI allowlist).
- Runs list links to `/ops/runs/{job}:{id}` detail.

### Run detail

- Overview metrics · Timeline · Output (error + JSON) · Events.

## Don’t

- Reintroduce Amigo frost, editorial heroes, or glass chips on ops routes.
- Duplicate Matching review as a top-level nav item.
- Put the four-stage journey strip on Inbox / list rows (detail and batch-selection workbench only).
- Auto-start Fulfillment from matching approve alone — Legal kickoff (and Access identity-comment when applicable) gate start.
- Call catalog-only verticals “coming soon,” or treat Auth0 / Mailchimp as coming soon (Auth0 is live; Mailchimp is retired).
- Label CA DROP as a system or connection chip (including next to Alumni). CA DROP is source-only; Test vertical uses System A / System B.
