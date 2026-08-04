"""Subprocess wrapper for dbt under transform/external_hash."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = ["DbtRunResult", "run_external_hash_dbt_build"]


@dataclass(frozen=True)
class DbtRunResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str


def run_external_hash_dbt_build(
    *,
    dbt_dir: str | Path,
    system: str,
    timeout_seconds: int,
    perform_serving_swap: bool = False,
) -> DbtRunResult:
    """Run dbt build for one external vertical system."""
    cwd = Path(dbt_dir)
    vars_json = json.dumps(
        {
            "system": system,
            "perform_serving_swap": perform_serving_swap,
        }
    )
    cmd = [
        "dbt",
        "build",
        "--select",
        f"tag:system_{system}",
        "--vars",
        vars_json,
    ]
    env = {
        **os.environ,
        "DBT_PROFILES_DIR": os.environ.get("DBT_PROFILES_DIR", str(cwd)),
    }
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        env=env,
    )
    return DbtRunResult(
        ok=completed.returncode == 0,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
