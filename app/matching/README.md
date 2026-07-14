# Matching

Consumer record matching for privacy requests, across all intake sources. A `MatchingPipeline`
interface with one adapter per source — `DropHashPipeline` (California DELETE Act: SHA-256 compare
against the drop hash index) and `PlaintextMatchPipeline` (webform / CSV: plaintext lookup, data
source TBD — MDR vs M Tool) — dispatched by a router keyed on `IntakeSource`. A future state-specific
matching requirement is a new adapter class, not a new app.

Cloud Run FastAPI app (scaffold pending). Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
**Design:** `Projects/Data Privacy/01-ARCHITECTURE/Decisions/ADR-21-DROP-Hash-Matching.md` (Addendum, 2026-07-13) + `05-DELIVERABLES/Matching-Design-Brief.md` in the KB.
