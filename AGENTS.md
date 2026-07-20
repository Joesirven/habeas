# Agent guide — data-privacy

Code repo for **Habeas Data Privacy Request Automation**. Design authority (architecture decisions, version 0 spec): `~/Documents/SirvenOS/Habeas/Projects/Data Privacy/`.

**Bitbucket:** `dsts/data-privacy` · **Branch:** `master` for integration; agent work on `agent/<slug>`.

---

## Session start

1. Read this file.
2. Read `AGENTS.md` in the directory you will edit (`> inherits` chain).
3. Load `.agent/modules/<name>.md` only when a gate below matches — just-in-time, not all at once.

---

## Repo map (layout v4)

| Path | Role |
|------|------|
| [`libs/habeas-privacy-core/`](libs/habeas-privacy-core/) | Shared library — models, queue, audit, adapter bases (not deployed alone) |
| [`transform/drop_hash/`](transform/drop_hash/) | dbt + UDF DROP hash index — prod home; serving marts `email_hash` / `phone_hash` / `ndz_hash` in `example-gcp-project.drop_hash_index` (not `analytics/`) |
| [`app/`](app/) | All Cloud Run FastAPI apps — control plane + automation |
| [`app/admin_api/`](app/admin_api/) | Main control-plane app — mutations, dashboard, live events |
| [`clients/web/`](clients/web/) | Admin web app — Vite, React, TypeScript, Bun; Drop ops Pipeline + Health |
| [`clients/cli/habeas-cli/`](clients/cli/habeas-cli/) | Habeas command-line — hybrid read/write |
| [`db/migrations/`](db/migrations/) | Unified database migrations (dbmate) |
| [`infra/`](infra/) | Cloud Build, Terraform, Docker |
| [`scripts/`](scripts/) | One-off ops scripts — not imported by production code |
| [`.agent/modules/`](.agent/modules/) | Repeatable workflows — load on gate match only |

**Python:** [UV](https://docs.astral.sh/uv/) only — `uv sync`, `uv run`, `uv lock`. Workspace members: `libs/*`, `app/*`, `clients/cli/*`. Never pip, venv, or poetry in this repo.

---

## Orchestration

Master agent **plans → delegates executors → separate reviewers → merges**. Disjoint file ownership per subagent. Large outputs go to `tmp/`, referenced by path.

If multi-file task → read [`.agent/modules/orchestration.md`](.agent/modules/orchestration.md).  
If pre-merge → read [`.agent/modules/review-personas.md`](.agent/modules/review-personas.md).

---

## Module gates (just-in-time)

| If you are… | Read |
|-------------|------|
| Editing Python | [`python-uv.md`](.agent/modules/python-uv.md) |
| Editing `db/migrations/` | [`db-migrations.md`](.agent/modules/db-migrations.md) |
| Deploy / prod migrate / CLI `--execute` | [`prod-write-gate.md`](.agent/modules/prod-write-gate.md) |
| Editing `clients/web/` | [`frontend-stack.md`](.agent/modules/frontend-stack.md) |
| Any UI / visual design | [`design-taste.md`](.agent/modules/design-taste.md) |
| DROP Ops IA UI (Runs / Requests / ops dashboard) | [`design-taste-ops-ia.md`](.agent/modules/design-taste-ops-ia.md) |
| Agent using Habeas CLI | [`cli-agent-interface.md`](.agent/modules/cli-agent-interface.md) |
| Touching request or audit tables | [`privacy-invariants.md`](.agent/modules/privacy-invariants.md) |

---

## Invariants

- No personally identifiable information in logs or audit payloads.
- **Mutations** only through `app/admin_api` (web and command-line write path).
- Deployed admin-api requires **Identity-Aware Proxy** identity (`REQUIRE_IAP_IDENTITY=true`); CLI uses `IAP_OAUTH_CLIENT_ID` + SA impersonation (`IAP_IMPERSONATE_SERVICE_ACCOUNT` / `IAP_ID_TOKEN`) — see `infra/README.md` and [`.agent/modules/cli-agent-interface.md`](.agent/modules/cli-agent-interface.md). Never call workers directly; never grant user→worker `run.invoker`.
- Command-line **SELECT-only** for ad-hoc analysis — no insert, update, delete, truncate.
- No production writes without Jose approval.
- No secrets in git.
- **snake_case** for directories and Python packages; **no acronyms** in agent files — spell terms out on first use.
- Do not duplicate knowledge-base content here — link to SirvenOS project folder.

---

## Do not

- Run raw SQL or `psql` in agent sessions — use Habeas CLI wrappers.
- Add a top-level `adapters/` or `utils/` directory.
- Edit accepted architecture decision records in the knowledge base from this repo.
- Commit credentials, `.env`, or connection strings.

---

## Commands

```bash
uv sync --all-packages
uv run --group dev pytest
uv run --package habeas-cli habeas-cli version
uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir app/admin_api/src
cd clients/web && bun install && bun run dev
dbmate -d db/migrations up
```
