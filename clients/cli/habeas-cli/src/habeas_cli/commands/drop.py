"""DROP pipeline + hash-index refresh commands (mutations via admin-api)."""

from __future__ import annotations

import typer

from habeas_cli.admin_api_client import AdminApiError, admin_api_request
from habeas_cli.output import emit

app = typer.Typer(help="DROP pipeline ops via admin-api")
hash_index_app = typer.Typer(help="Hash index refresh queue + worker")
app.add_typer(hash_index_app, name="hash-index-refresh")


@app.command("pipeline")
def pipeline(human: bool = typer.Option(False, "--human")):
    """GET /ops/drop/pipeline status snapshot."""
    try:
        payload = admin_api_request("GET", "/ops/drop/pipeline")
    except AdminApiError as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc
    emit(payload, human=human)


@hash_index_app.command("status")
def hash_index_status(human: bool = typer.Option(False, "--human")):
    """Show hash_index_refresh slice of pipeline status."""
    try:
        payload = admin_api_request("GET", "/ops/drop/pipeline")
    except AdminApiError as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc
    emit(
        {
            "hash_index_refresh": payload.get("hash_index_refresh"),
            "worker_health": {
                "hash_index_refresh": (payload.get("worker_health") or {}).get(
                    "hash_index_refresh"
                )
            },
        },
        human=human,
    )


@hash_index_app.command("enqueue")
def hash_index_enqueue(
    state: str = typer.Option("CA", "--state"),
    all_states: bool = typer.Option(
        False,
        "--all-states",
        help="Enqueue refresh for every served state (USPS 50+DC)",
    ),
    execute: bool = typer.Option(False, "--execute"),
    human: bool = typer.Option(False, "--human"),
):
    """Enqueue hash-index refresh (single-flight per state, or all served states)."""
    if all_states:
        body: dict = {"list_types": ["NDZ", "Email", "Phone"]}
        path = "/ops/drop/hash-index-refresh/enqueue-all"
    else:
        body = {"state": state, "list_types": ["NDZ", "Email", "Phone"]}
        path = "/ops/drop/hash-index-refresh/enqueue"
    if not execute:
        emit({"dry_run": True, "would_post": body, "path": path}, human=human)
        return
    try:
        payload = admin_api_request(
            "POST",
            path,
            json_body=body,
        )
    except AdminApiError as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc
    emit(payload, human=human)


@hash_index_app.command("process")
def hash_index_process(
    execute: bool = typer.Option(False, "--execute"),
    human: bool = typer.Option(False, "--human"),
):
    """Proxy process to hash_index_refresh worker."""
    if not execute:
        emit({"dry_run": True, "would_post": "/ops/drop/hash-index-refresh/process"}, human=human)
        return
    try:
        payload = admin_api_request("POST", "/ops/drop/hash-index-refresh/process")
    except AdminApiError as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc
    emit(payload, human=human)


@app.command("match")
def match(
    execute: bool = typer.Option(False, "--execute"),
    human: bool = typer.Option(False, "--human"),
):
    """Kick matching worker process via admin-api."""
    if not execute:
        emit({"dry_run": True, "would_post": "/ops/drop/match"}, human=human)
        return
    try:
        payload = admin_api_request("POST", "/ops/drop/match")
    except AdminApiError as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc
    emit(payload, human=human)
