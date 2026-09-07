---
title: "Owner mapping workbench + list-type capability gates"
date: 2026-09-02
type: feat
topic: mapping-list-type-gates
artifact_contract: ce-unified-plan/v1
artifact_readiness: requirements-only
product_contract_source: ce-brainstorm
execution: code
---

## Goal Capsule

**Objective.** After a data owner connects or uploads an external system, give them a live, reversible mapping workbench (header row → column→variable assign → format/clean). Derive Email / Phone / NDZ support from which canonical variables are complete, and gate hash-refresh, dbt select, ensure-drain, chunk matching, and dispatch enqueue on that capability (with `DISPATCH_VERTICAL_LIST_TYPES` only as an ops flood valve).

**Product authority.** Congruence lock from `agent/external-phone-ndz-marts` (separate per-kind external marts; one hashed-raw grain; canonical keys `email` / `phone` / `first_name` / `last_name` / `dob` / `zip`; DROP CPPA hashing). Design authority: SirvenOS Data Privacy project folder. Prior mapping discussion: agent transcript `b222ce68-70a0-4f75-b1d7-437c65e6cf77`.

**Open blockers.** Jose-approved-empty ritual for mapped-but-empty marts (product/ops, not UI yet). Live systems (Auth0) need catalog capability, not CSV mapping. Sample designs / lab route pending parallel-orchestrate §1.

## Product Contract

### Problem framing

Phone/NDZ vertical matching and marts exist (or are landing), but owners still map columns on a thin “any one field is enough” path. Dispatch defaults to Email-only via env. Mapping is not yet the source of truth for which DROP list types a connection supports, so enqueue and drain can disagree with what the owner actually uploaded.

### Actors

- Primary: **data owner** completing or revisiting mapping after connect/upload.
- Secondary: **ops / super_admin** setting the flood valve and Jose-approved empty.
- Not actors for list choice: owners do not toggle which lists to match.

### Key decisions

- KD1. Capability is **mapping-derived (hard)** — completeness of canonical variables decides Email / Phone / NDZ. Rejected: owner list toggles; env as primary capability. `(session-settled: user-directed — chosen over toggles/env-primary: owners map columns only)`
- KD2. Post-connect journey includes **capability clarity, NDZ path, and revisit** — not a single disposable wizard screen. `(session-settled: user-directed — chosen over single-gap fixes: all of the above)`
- KD3. Mapping steps: **header-row options → column→variable assign → format/clean**; interactive, reversible, **live** preview. Owners do not decide lists; lists follow available variables. `(session-settled: user-directed — chosen over list-type toggles)`
- KD4. **Unmapped ≠ empty mart.** Unmapped/cannot-support: never enqueue, never build that kind’s mart for matching readiness, never drain that list type. Mapped + missing mart: fail-closed retry. Mapped + empty must not silently succeed as zero-hit until Jose-approved empty or non-empty refresh. Flood valve remains. `(session-settled: user-directed — chosen over treat-empty-as-unsupported or soft zero-hit)`
- KD5. **Partial NDZ ignored** — save allowed; NDZ unsupported until all four of first_name, last_name, dob, zip are mapped. `(session-settled: user-directed — chosen over block-save / warn-block)`
- KD6. Canonical keys stay `email`, `phone`, `first_name`, `last_name`, `dob`, `zip` (+ header aliases); `multi_pii_delimiter` for email/phone cells. No new keys. `(session-settled: user-directed — congruence lock)`
- KD7. Live systems (Auth0): catalog capability (email+phone yes, NDZ never); same gate matrix, different capability source. Test vertical System B follows upload mapping; System A / CA DROP never become connection chips or capability sources.

### Requirements

- R1. After connect/upload success, owner can open a durable mapping workbench and revisit it later.
- R2. Workbench lets owner set header-row options, assign source columns to canonical variables, and set format/clean options with live preview; all steps reversible.
- R3. UI derives and displays enabled DROP list types (Email / Phone / NDZ) from mapping completeness; never asks the owner to pick lists.
- R4. Email enabled when `email` mapped; Phone when `phone` mapped; NDZ only when all four name/DOB/ZIP fields mapped. Partial NDZ does not enable NDZ.
- R5. At mapping save, persist mapping (+ formats/delimiter as today) and derived capability preview; do not invent new canonical keys.
- R6. Hash-refresh / dbt select builds only kinds the connection’s capability enables (plus Live catalog rules for Auth0).
- R7. `ensure_drain` readiness considers connection freshness and mart readiness for **enabled** kinds — not “any mart exists” when that mart’s kind is unsupported.
- R8. `process_matching_chunk` only processes attempts for enabled kinds; missing mart for an enabled kind fail-closes with retry; must not treat empty-unapproved mart as successful zero-hit.
- R9. Request dispatcher enqueues vertical attempts only for `DISPATCH_VERTICAL_LIST_TYPES ∩ mapped (or catalog) capability`. Flood valve never invents support the mapping lacks.
- R10. Distinguish cannot-support (unmapped / Auth0 NDZ) from not-ready (mapped, mart missing or empty without Jose approval) in owner/ops-facing status copy without PII.

### Gate matrix

| Gate | Mapped / catalog-enabled kind | Unmapped / cannot-support | Mapped + mart missing | Mapped + empty (not Jose-approved) |
|------|-------------------------------|---------------------------|------------------------|-------------------------------------|
| Mapping save | OK; preview shows enabled lists | Partial NDZ → NDZ off | n/a | n/a |
| Hash-refresh / dbt select | Build only enabled kinds | Skip that kind | May create table; not match-ready | Not match-ready |
| ensure-drain | Ready when gate OK and ≥1 enabled kind has ready mart | Ignore disabled kinds | Not ready for that kind’s work | Not match-ready |
| process_matching_chunk | Lookup enabled kinds | Must not see these attempts | Fail-closed retry | Fail-closed / not success-zero-hit |
| Dispatcher enqueue | Flood valve ∩ capability | Never enqueue | Prefer not enqueue until mart ready | Prefer not enqueue until approved/non-empty |

### Mapping step list (wireframe outline)

1. **Land** — connect or upload succeeded; CTA to map columns (or resume incomplete mapping).
2. **Header row** — choose/confirm which row is headers; live sample of detected headers.
3. **Assign** — map source headers → canonical variables; show live enablement chips for Email / Phone / NDZ (derived).
4. **Format / clean** — email/phone/name formats and multi-PII delimiter where mapped; live sample validation counts (no raw PII in logs).
5. **Confirm** — summary of enabled lists + what remains unsupported; save; hash-refresh may follow per existing cadence.

### Scope boundaries

**In scope.** Owner mapping workbench UX; derived capability; gates at save, hash-refresh, dbt select, ensure-drain, chunk process, dispatch; Auth0 catalog exception; lab route for mapping UX when parallel-orchestrate requires it.

**Out of scope / non-goals.** DROP Data mart schema changes; prod deploy without Jose; owner list-type toggles; new canonical mapping keys; replacing congruence-locked external mart / hashed-raw shapes; making CA DROP a connection chip.

**Deferred.** Jose-approved-empty operator UI/API shape; retiring `DISPATCH_VERTICAL_LIST_TYPES` entirely after all verticals are mapping-gated and marts are routinely ready.

### Success criteria

- Owner can complete header → assign → format without choosing lists, and see which of Email / Phone / NDZ are enabled.
- Unmapped Phone/NDZ never enqueue for that connection; mapped missing mart does not close as zero-hit success.
- Flood valve can still hold Phone/NDZ enqueue globally until ops cutover.
- Hermetic tests cover capability derivation and each gate row; no PII in logs/audit.

### Assumptions

- A1. `full_name` UI convenience may remain for formats, but NDZ enablement requires the four canonical parts (split or derived) — planning resolves how full_name interacts without new keys.
- A2. “Mart ready” for empty tables means Jose-approved empty or non-empty after refresh — exact storage of the approval flag is planning-owned.
- A3. Sibling branch `agent/external-phone-ndz-marts` remains the mart/matching substrate; this work builds gates + UX on top.

### Dependencies

- External phone/NDZ marts + drain list_type routing (sibling branch / landed plumbing).
- Existing `metadata.column_mapping` persist path on owner connectors.
- Design taste + frontend-stack modules for any lab/production owner UI.
