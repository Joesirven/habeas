# module: python-uv

> Gate: editing any Python under `libs/`, `app/`, or `clients/cli/`.

## Rules

- Run from repo root: `uv sync`, `uv lock`, `uv run --package <name> …`
- Workspace members: `libs/*`, `app/*`, `clients/cli/*` — see root `pyproject.toml`
- Depend on core: `habeas-privacy-core = { workspace = true }`
- Docker builds: `uv sync --frozen --no-dev --package <app_name>` from repo root context
- Never pip install, poetry, or manual venv in this repo
- Lint: ruff + mypy (when configured)

## Add a new app

1. Create `app/<snake_case_name>/pyproject.toml` as workspace member.
2. Import models from `habeas_privacy_core.models` — do not duplicate.
3. Add Cloud Run Dockerfile + infra trigger (path-filtered).
