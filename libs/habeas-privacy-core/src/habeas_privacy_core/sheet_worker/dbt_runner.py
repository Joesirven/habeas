"""Subprocess wrapper for dbt under transform/external_hash (sheet marts).

Warehouse auth is inherited from the environment (``DBT_PROFILES_DIR`` + ADC).
This module never hardcodes project, dataset, or credentials, and does not log
captured dbt stdout/stderr.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from habeas_privacy_core.connections.catalog import (
    ListCapability,
    filter_dbt_select,
)
from habeas_privacy_core.sheet_worker.config import SheetWorkerConfig

__all__ = ["DbtRunResult", "run_external_hash_dbt_build"]


@dataclass(frozen=True)
class DbtRunResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str


def run_external_hash_dbt_build(
    config: SheetWorkerConfig,
    *,
    dbt_dir: str | Path,
    timeout_seconds: int,
    capability: ListCapability | None = None,
) -> DbtRunResult:
    """Run ``dbt build`` for one sheet system's staging + enabled-kind marts."""
    select = config.dbt_select
    if capability is not None:
        select = filter_dbt_select(select, capability)
    if not select:
        return DbtRunResult(ok=True, returncode=0, stdout="", stderr="")

    cwd = Path(dbt_dir)
    cmd = ["dbt", "build", "--select", *select]
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
