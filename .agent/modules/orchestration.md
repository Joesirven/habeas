# module: orchestration

> Applies to: master agent on any multi-file task.  
> Inherits: SirvenOS `Habeas/Ops/System/modules/subagent-orchestration.md` (same rules).

## Rules

- Plan first; write plan to `tmp/` before fan-out.
- **Executor** subagents own disjoint file sets — no two writers on one file.
- **Reviewer** subagents are separate from executors (maker → checker).
- After review, spawn quality-control / quality-assurance (QCQA) testers for any multi-file or production-path change — they **run** hermetic suites, not code-read-only. See [`review-personas.md`](review-personas.md) § Testing quality-control / quality-assurance.
- Subagents return paths, not large pasted content.
- Parallelize independent work; serialize only on true dependency.
- Record resulting decisions in SirvenOS `decisions.md` under key `data-privacy/<topic>` when architecture changes.

## Personas

| Persona | Role |
|---------|------|
| Planner | Breaks work, assigns files, stays orchestrating |
| Executor | Implements one subtree |
| Reviewer | Checks executor diff — security, privacy, correctness per change type |
| QCQA tester | Executes hermetic tests; writes `/tmp/qcqa-<persona>-<slug>.md` |

See [`review-personas.md`](review-personas.md) for which reviewers to spawn and the Testing QCQA suites.

## Testing quality-control / quality-assurance

Mandatory for multi-file or production-path work. QCQA personas must **execute** hermetic tests (`DATABASE_URL=""` for pytest). Code-read-only QCQA is a **priority-zero (P0) process failure**.

Commands, area invariants, and report path: [`review-personas.md`](review-personas.md) § Testing quality-control / quality-assurance. UV and package layout: root [`AGENTS.md`](../../AGENTS.md). Do not duplicate those files here.
