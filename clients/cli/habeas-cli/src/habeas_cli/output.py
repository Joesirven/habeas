"""JSON / human CLI output helpers."""

from __future__ import annotations

import json
from typing import Any

import typer

CLI_VERSION = "1.0"


def emit(payload: dict[str, Any], *, human: bool = False) -> None:
    payload.setdefault("version", CLI_VERSION)
    if human:
        typer.echo(json.dumps(payload, indent=2, default=str))
    else:
        typer.echo(json.dumps(payload, default=str))
