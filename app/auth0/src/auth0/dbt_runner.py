"""Subprocess wrapper for dbt under transform/external_hash (Auth0 marts only).

Warehouse auth is inherited from the environment (``DBT_PROFILES_DIR`` + ADC).
This module never hardcodes project, dataset, or credentials, and does not log
captured dbt stdout/stderr (those streams may contain table ids or hashes).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Auth0 models only — do not build other verticals.
AUTH0_DBT_SELECT = ("stg_auth0_hashed", "mart_auth0_email_hash")


@dataclass(frozen=True)
class DbtRunResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str


def run_external_hash_dbt_build(
    *,
    dbt_dir: str | Path,
    timeout_seconds: int,
) -> DbtRunResult:
    """Run ``dbt build`` for Auth0 staging + email-hash mart.

    Command (cwd = ``dbt_dir``)::

        dbt build --select stg_auth0_hashed mart_auth0_email_hash

    ``DBT_PROFILES_DIR`` is set to the existing env value, or ``dbt_dir`` when
    unset. ``subprocess.TimeoutExpired`` is left for the caller to handle.
    """
    cwd = Path(dbt_dir)
    cmd = [
        "dbt",
        "build",
        "--select",
        *AUTH0_DBT_SELECT,
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
