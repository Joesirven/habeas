---
title: "feat: Super-admin Ops command-center IA"
date: 2026-07-30
type: feat
topic: ops-command-center-ia
artifact_contract: ce-unified-plan/v1
artifact_readiness: requirements-only
product_contract_source: ce-brainstorm
execution: code
---

# Super-admin Ops command-center IA - Plan

## Goal Capsule

**Objective:** Collapse overlapping super-admin Ops surfaces into a **command-center Home** plus a **hybrid Inbox** (system + human escalations) with deep, agent-ready error triage — so operate / triage / health aren’t scattered across duplicate dashboards, shells, and log tabs.

**Product authority:** This Product Contract (session-settled choices below) > prior Ops IA plan (`docs/plans/2026-07-17-001-feat-drop-ops-ia-plan.md`) for nav grouping updates > `clients/web/AGENTS.md` / `.agent/modules/design-taste-ops-ia.md` (update when implementing).

**Open blockers:** None for planning. Escalation object model and auto-escalation rules are deferred to planning (see Deferred).

---

## Product Contract

### Summary

Super-admin Home becomes a dense **status board** (fleet health, failure counts, pipeline pulse). Opening a red signal goes to **Inbox**, the single escalation work queue for system failures (runs, batches, workers, stuck pipeline) and human escalations from legal/admin. Opened items show deep triage detail suitable to copy for an agent. Overlapping Ops peers (duplicate dashboard, Incidents/Jobs shells, Insights-as-peer, standalone Errors/Logs as top peers) fold into this path. **Configure** holds schedules, connections, and retry. DROP **mutation console** actions stay off the status board as the primary power surface.

### Problem Frame

Ops grew as Prefect/Dagster-inspired peers (Dashboard, Workers, Runs, Jobs, Insights, Incidents) plus a DropPipeline console that also became Home. Super-admin now sees overlapping health and failure surfaces, thin shells into `listRuns`, and two dashboards. Errors/Logs were added as Dashboard tabs, increasing overlap. Inbox today surfaces request-grain needs-attention items that don’t match super-admin triage (find error → deep detail → hand to agent), while legal/admin still need a way to escalate problems to super-admins.

### Key Decisions

- KD1. (session-settled: user-directed — chosen over quiet counts-only board / Observe·Act·Configure modes) **Variant B — command-center Home:** denser Home with health + failure preview + pipeline pulse; Inbox still owns triage work items.
- KD2. (session-settled: user-directed — chosen over failures-only or pipeline-first home) Home answers **health and failures first**; pipeline correctness is a **drill from a red signal**, not the default first story.
- KD3. (session-settled: user-directed — chosen over collapse-only or deep-triage-only) Ship **both** a smaller Ops map **and** deep triage (agent-ready error packages).
- KD4. (session-settled: user-directed — chosen over system-only or request-only Inbox) Super-admin Inbox is **hybrid**: legal/admin can escalate errors to super-admins; the system also escalates runs, batch runs, requests, workers, and related stuck work.
- KD5. (session-settled: user-directed — chosen over dual failure homes or human-only Inbox) **Inbox is the escalation queue**; Home shows snapshot + counts and deep-links into Inbox (same escalation objects).
- KD6. (session-settled: user-approved — synthesis call-outs confirmed) “Compatible with other roles’ Inbox” means **shared Inbox chrome / lane pattern**, not the same default object mix — request matching volume stays out of the super-admin **default** queue.
- KD7. (session-settled: user-approved — synthesis call-outs confirmed) **Run Pipeline / hash refresh mutations** stay under Configure or a secondary Pipeline expand — not competing with the Home status board as the primary chrome.
- KD8. Prior plan constraint retained: DROP **mutation console** remains a gated power surface; do not absorb mutations into Home as the main operator story. `(session-settled: user-approved — carried from drop-ops-ia plan KTD2; not re-opened here.)`

### Requirements

**Home (command center)**

- R1. Super-admin Home presents fleet health, open-escalation / failure counts, and a read-only pipeline pulse (stuck or attention stages) in one composition.
- R2. Clicking a Home failure or escalation count opens Inbox focused on that escalation (or equivalent deep-link), not a third orphan page.
- R3. Home does not become the primary DROP mutation console; Run Pipeline and hash refresh remain reachable from Configure or a secondary Pipeline expand.

**Inbox (hybrid escalations)**

- R4. Super-admin Inbox surfaces **system** escalations (failed/stuck runs, batch/pipeline blockers, worker downs, and related) and **human** escalations created by legal or admin.
- R5. Legal and admin can escalate an error or blocked item they encounter to super-admins; the escalation appears in the super-admin Inbox.
- R6. Super-admin default Inbox lanes prioritize hybrid escalations; request matching / case volume is not the default primary feed (other roles keep their request-grain Inbox behavior).
- R7. Inbox chrome remains recognizably the same pattern other roles use (list + detail / lanes), with role-appropriate content and lanes.

**Deep triage**

- R8. Opening an escalation shows deep detail: severity, resource, message, links to run and/or request when applicable, and a **copy-for-agent** package (privacy-safe: ids/counts/redacted errors only — no PII, hashes, or dwids).
- R9. Standalone top-level Errors/Logs peers are not required once deep triage lives on Inbox (and optional filters within that detail); historical Dashboard Errors/Logs tabs may be removed or demoted when the Inbox path ships.

**Ops map collapse**

- R10. Duplicate `/ops/dashboard` overview and thin shells that only filter Runs (Incidents, Jobs) are absorbed into Home counts and/or Inbox system escalations — not kept as peer destinations with the same job.
- R11. Fleet health currently repeated across Workers / Health(Insights) / Home collapses so Home owns the snapshot; worker settings and connections live under Configure (or Workers-as-settings), not a third “insights” peer with the same metrics.
- R12. Top navigation for super-admin exposes a small set: Home, Inbox, Configure (plus existing Requests/Docs as today). Pipeline is drill/expand, not a competing peer for the first viewport.

**Privacy and roles**

- R13. Escalation and log payloads remain privacy-safe (ids, counts, redacted errors). No vendor PII in UI or copy-for-agent packages.
- R14. Non–super_admin roles keep their current Request / Inbox product surfaces; they do not gain the Ops command-center Home.

### Actors

- A1. Super admin — operates platform health, triages escalations, hands errors to agents.
- A2. Legal / admin — escalate blocked or erroneous work to super-admins; keep request-grain Inbox.
- A3. Agent (via operator paste) — consumer of copy-for-agent error packages (not a logged-in UI role).

### Key Flows

- F1. Super admin opens Home → sees worker/queue health and escalation counts → clicks a failure → Inbox opens on that item → copies agent package → investigates or remediates.
- F2. System detects failed run / worker down / stuck batch → creates or updates a system escalation → Home count increments → appears in super-admin Inbox System lane.
- F3. Legal or admin hits a blocker → Escalates to super-admin → human escalation appears in super-admin Inbox Human lane with context links (request/run when applicable).
- F4. From an Inbox system escalation tied to pipeline stuckness → operator drills into pipeline stage context without making Pipeline the Home default.

### Acceptance Examples

- AE1. With one worker down and three failed matching runs, Home shows both signals; clicking either lands in Inbox on the corresponding escalations — not on a separate Incidents shell.
- AE2. Legal escalates a stuck fulfillment item; a super-admin sees it under Human (or equivalent) without it being buried under matching-review volume.
- AE3. Opening a system ERROR escalation shows redacted error text and Copy for agent; pasted package contains no email, hash, or dwid.
- AE4. Super-admin default Inbox is not dominated by matching-review request rows that belong to data-owner/legal case work.
- AE5. Run Pipeline is not the dominant first-viewport control on Home; it remains reachable from Configure or secondary Pipeline expand.
- AE6. `/ops/incidents` and `/ops/jobs` are gone or redirect into Inbox/Home deep-links; operators are not taught two parallel failure UIs.

### Scope Boundaries

**In:** Super-admin Home regrouping; hybrid Inbox content/lanes for super_admin; deep triage / copy-for-agent; collapsing overlapping Ops peers and Dashboard Errors/Logs-as-peers; Configure placement for schedules/connections/retry; nav/docs updates for the new map.

**Out:** Absorbing DROP mutation console into Home as primary; changing legal/admin request Inbox into ops-system grain; production Incidents ownership/ack product beyond escalations-as-queue; making GCP Cloud Logging the primary feed (DB attempt + audit + escalation records remain the product source unless planning proves a gap); data_owner Ops surfaces.

### Deferred to Follow-Up Work / Planning

- Exact escalation persistence model (new table vs reuse assignment/approval patterns) and auto-escalation rule thresholds.
- Whether Workers remains a settings-heavy sub-route under Configure or a named Configure tab.
- Whether pipeline pulse on Home is live bulk-process summary only or also includes vertical workers.
- Optional later: GCP Cloud Logging deep-link or proxy for stdout beyond persisted attempt/audit fields.

### Success Criteria

- A super-admin can answer “is the platform healthy?” and “what’s broken?” from Home without visiting three peer health pages.
- Triage of a failure is one click into Inbox with enough detail to hand an agent a privacy-safe package.
- Legal/admin escalations and system escalations share one super-admin queue without replacing other roles’ request Inbox.
- Ops peer count drops: no duplicate dashboards or shell-only Incidents/Jobs as taught destinations.

### Assumptions

- Existing admin-api aggregates (`/ops/drop/pipeline`, workers, health queues, `/ops/runs`, `/ops/logs`) remain the data backbone; planning invents escalation persistence, not a new observability stack.
- “Compatible Inbox” is UX pattern compatibility across roles, confirmed in KD6.
