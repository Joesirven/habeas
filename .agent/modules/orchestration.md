# module: orchestration

> Applies to: master agent on any multi-file task.  
> Inherits: SirvenOS `Habeas/Ops/System/modules/subagent-orchestration.md` (same rules).

## Rules

- Plan first; write plan to `tmp/` before fan-out.
- **Executor** subagents own disjoint file sets — no two writers on one file.
- **Reviewer** subagents are separate from executors (maker → checker).
- Subagents return paths, not large pasted content.
- Parallelize independent work; serialize only on true dependency.
- Record resulting decisions in SirvenOS `decisions.md` under key `data-privacy/<topic>` when architecture changes.

## Personas

| Persona | Role |
|---------|------|
| Planner | Breaks work, assigns files, stays orchestrating |
| Executor | Implements one subtree |
| Reviewer | Checks executor diff — security, privacy, correctness per change type |

See [`review-personas.md`](review-personas.md) for which reviewers to spawn.
