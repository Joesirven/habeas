"""Thin dbmate wrapper for local dev and integration tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def repo_root() -> Path:
    """Locate monorepo root by walking up to pyproject.toml + db/migrations."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "db" / "migrations").exists():
            return parent
    raise RuntimeError("Could not locate data-privacy repo root")


def migrations_dir() -> Path:
    return repo_root() / "db" / "migrations"


def run_migrations(*, database_url: str, migrations_path: Path | None = None) -> None:
    """Apply pending dbmate migrations."""
    dbmate = shutil.which("dbmate")
    if dbmate is None:
        raise RuntimeError("dbmate is not installed or not on PATH")

    path = migrations_path or migrations_dir()
    env = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run([dbmate, "-d", str(path), "up"], check=True, env=env)


def migration_status(*, database_url: str, migrations_path: Path | None = None) -> str:
    """Return dbmate status output."""
    dbmate = shutil.which("dbmate")
    if dbmate is None:
        raise RuntimeError("dbmate is not installed or not on PATH")

    path = migrations_path or migrations_dir()
    env = {**os.environ, "DATABASE_URL": database_url}
    result = subprocess.run(
        [dbmate, "-d", str(path), "status"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    return result.stdout
