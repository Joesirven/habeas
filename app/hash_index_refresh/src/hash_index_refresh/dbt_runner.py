"""Subprocess wrapper for dbt build under transform/drop_hash."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from hash_index_refresh.redaction import redact_stderr


@dataclass(frozen=True)
class DbtRunResult:
    """Outcome of a dbt build invocation."""

    success: bool
    exit_code: int
    duration_seconds: float
    stderr: str
    stdout: str
    error_message: str | None = None


def run_dbt_build(
    *,
    dbt_dir: Path,
    state: str,
    timeout_seconds: int,
) -> DbtRunResult:
    """Run ``dbt build`` with a state variable in the dbt project directory."""
    if not dbt_dir.is_dir():
        return DbtRunResult(
            success=False,
            exit_code=-1,
            duration_seconds=0.0,
            stderr="",
            stdout="",
            error_message=f"dbt project directory not found: {dbt_dir}",
        )

    vars_json = json.dumps({"state": state.upper()})
    command = [
        "dbt",
        "build",
        "--vars",
        vars_json,
        "--select",
        "marts",
        "drop_clean",
    ]
    env = {"DBT_PROFILES_DIR": str(dbt_dir)}
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=dbt_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env={**os.environ, **env},
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        stderr = redact_stderr(exc.stderr or "dbt build timed out")
        return DbtRunResult(
            success=False,
            exit_code=-1,
            duration_seconds=duration,
            stderr=stderr,
            stdout=redact_stderr(exc.stdout or ""),
            error_message="dbt build timed out",
        )

    duration = time.monotonic() - started
    stderr = redact_stderr(completed.stderr or "")
    stdout = redact_stderr(completed.stdout or "")
    if completed.returncode == 0:
        return DbtRunResult(
            success=True,
            exit_code=0,
            duration_seconds=duration,
            stderr=stderr,
            stdout=stdout,
        )

    detail = stderr.strip() or stdout.strip() or f"dbt exited with code {completed.returncode}"
    return DbtRunResult(
        success=False,
        exit_code=completed.returncode,
        duration_seconds=duration,
        stderr=stderr,
        stdout=stdout,
        error_message=detail,
    )
