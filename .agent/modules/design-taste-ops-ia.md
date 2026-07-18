# module: design-taste-ops-ia

> Gate: DROP Ops IA UI in `clients/web` — Runs, Requests, Ops dashboard, request journey, needs-attention, AppShell ops chrome.  
> For marketing / non-ops surfaces, prefer [`design-taste.md`](design-taste.md) (Amigo Habeas frosted).

**Source run:** `~/taste` · curated refs `reference-images/ops-ia-amigo-prefect-dagster/` (20 images) · skill name `habeas-ops-amigo-prefect-dagster`  
**Corpus:** Amigo + Bevel (agent chat / frost overlays) + Legora (metrics whitespace) + Habeas palette + Prefect dashboards/queues/run detail + Dagster Runs/event logs/insights/lineage.  
**Note:** Hosted Taste `npm run taste` failed on Vercel AI Gateway credits; skill synthesized via the same pipeline stages (corpus → image notes → rules → skill) using visual agents on those refs.

---

# habeas-ops-amigo-prefect-dagster

## Use this skill when

Building or restyling **Habeas Data Privacy admin ops** UI: Request / Job / Run surfaces, Prefect-style overview density, Dagster-style runs tables and journey/lineage rails — while keeping Habeas Amigo frost and brand blues.

Do **not** use this skill to invent a purple Dagster skin, a full dark Prefect theme, or a second unrelated design system.

## Brand lock (non-negotiable)

| Role | Hex | Use |
|------|-----|-----|
| Primary navy | `#1E4191` | Brand, headings accents, key CTAs, active nav |
| Mid blue | `#2B7BB9` | Charts, active filters/tabs, primary links |
| Light blue | `#428BCA` | Soft fills, focus, secondary controls |
| Canvas | `#F7F9FC` | Page ground |
| Surface | `#FFFFFF` | Tables, panels |
| Body | `#5E5E5E` / ink tokens | Secondary text |

Neutrals: cool off-white / pale blue-gray. No terracotta-as-default, cream-luxury, or purple gradients.

## Core directive

**Two modes, one system:**

1. **Editorial frost (Amigo / Bevel / Legora)** — matte frosted overlays, serif display for page titles, micro labels, generous margins on non-table chrome.
2. **Ops density (Prefect / Dagster)** — table-first / rail-first composition; compact rows; status pills; filter tabs; one volume strip; horizontal stage rails.

On ops routes, **density wins the primary zone**. Editorial frost wraps the shell; it must not inflate Runs/Requests into landing pages.

## Visual grammar

1. App shell: sticky frosted header (blur ~30px, translucent fill, quiet border), Habeas wordmark, compact nav.
2. Page chrome: small-caps / `taste-micro` eyebrow (`REQUESTS`, `OPS · RUNS`) → compact title (`text-xl`–`2xl`, not 3rem heroes) → optional one-line support.
3. Primary zone = **dense table, filter bar, or stage rail** — not equal-weight marketing KPI tiles.
4. Status as **pills/dots** (success green, fail red, in-flight mid-blue pulse, waiting outlined mid-blue) — not traffic-light emoji rows.
5. Filters: status **tabs** (All / Failed / In progress / Success) + window pills (8h / 24h / 1w) + job select; sync to URL search params.
6. Tables: `text-xs`, tight row padding, mono IDs, secondary metadata stacked under primary cell (Dagster Runs pattern).
7. Request journey: **horizontal stage rail** (opacity/weight for complete vs waiting vs running) + optional vertical detail; timestamps on nodes.
8. Dashboard: one **volume strip/chart** + compact tally row + failed escalation list + worker pool column (Prefect overview).
9. Frost chips for source/job tags; matte panels (`taste-panel`) — no glossy multi-layer shadows.
10. Agent/assist patterns (Bevel): reserved for future “ask ops” — frosted overlay, processing meta (“Thought for N seconds”); do not clutter v1 Runs tables with chat chrome.
11. Legora metrics: label-above-value for KPI tallies; whitespace above the fold on home “Needs me”, density below.
12. Lineage/graph (Dagster): left-to-right compact nodes, navy labels, light-blue edges — only when a real graph exists; otherwise horizontal rail is enough.

## Composition recipes

### Runs list (Dagster Runs)

- Status sub-tabs + window + job filter.
- Columns: run id (link) · status pill · job · request · started · duration.
- Row height compact; auto-refresh chip OK.

### Request list / needs-attention

- Table-first; row opens journey.
- Attention reason chip when present; stage column when API provides it.
- Header link to Needs attention queue.

### Request detail (journey)

- Compact mono request id header.
- Tabs: Overview | Journey | Matching.
- Horizontal rail primary; “Runs for request” for super_admin → `/ops/runs?request_id=…`.

### Ops dashboard (Prefect)

- Window control + volume strip (bucketed bars from runs).
- Compact tallies (total / failed / in flight / workers up).
- Failed escalation with deep links preserving `status` + `window`.
- Worker health column.

### Home `/` (Needs me)

- Primary: needs-attention count + Open queue.
- Admin: matching review + insights.
- Super_admin only: ops shortcuts (dashboard, runs, console).

## Do / Don’t

**Do**

- Keep Amigo frost on shell and chips.
- Prefer URL-driven filters.
- Use Habeas blues for interactive accents.
- Show honest shells for Jobs / Incidents / SLAs until products exist.

**Don’t**

- Copy Prefect full dark theme or Dagster purple.
- Use 2.5–3rem display heroes on ops tables.
- Equal four soft KPI cards as the whole dashboard.
- Map `waiting` stages to “running” visually.
- Call worker URLs from the browser.

## Implementation anchors (this repo)

- Tokens / classes: `clients/web` `taste-*`, Habeas CSS variables in global styles.
- Nav IA: Requests / Ops / Console — see `clients/web/AGENTS.md`.
- Deploy surface for this IA: Cloud Run **`ops-ia-web-dev`** (IAP front door; `/api` proxied to admin-api). Prefer that URL over contested `admin-web-dev` while other agents iterate.

## Provenance

| Stage | Artifact |
|-------|----------|
| Corpus | 20 images under `~/taste/reference-images/ops-ia-amigo-prefect-dagster/` |
| Notes | Agent visual synthesis (Amigo/Bevel/Legora + Prefect/Dagster), 2026-07-17 |
| Skill | This module — `habeas-ops-amigo-prefect-dagster` |
| Prior | Supersedes ops sections of `amigo-habeas-frosted` for ops routes only |
