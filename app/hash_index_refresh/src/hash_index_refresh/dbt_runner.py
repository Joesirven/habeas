"""Subprocess wrapper for dbt under transform/drop_hash."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DbtRunResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str


def run_dbt_build(
    *,
    dbt_dir: str | Path,
    state: str,
    timeout_seconds: int,
) -> DbtRunResult:
    cwd = Path(dbt_dir)
    vars_json = json.dumps({"state": state})
    cmd = [
        "dbt",
        "build",
        "--vars",
        vars_json,
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return DbtRunResult(
        ok=completed.returncode == 0,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
