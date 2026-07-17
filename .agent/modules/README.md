# Agent modules

Just-in-time workflow files. Load only when root `AGENTS.md` gate matches — do not read all at session start.

| Module | Gate |
|--------|------|
| [`orchestration.md`](orchestration.md) | Multi-file task |
| [`python-uv.md`](python-uv.md) | Python edits |
| [`db-migrations.md`](db-migrations.md) | `db/migrations/` |
| [`prod-write-gate.md`](prod-write-gate.md) | Prod deploy / `--execute` |
| [`frontend-stack.md`](frontend-stack.md) | `clients/web/` |
| [`design-taste.md`](design-taste.md) | Any UI / visual design |
| [`cli-agent-interface.md`](cli-agent-interface.md) | Habeas CLI |
| [`privacy-invariants.md`](privacy-invariants.md) | Request / audit code |
| [`review-personas.md`](review-personas.md) | Pre-merge review |
