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
    state: str | None = typer.Option(
        None,
        "--state",
        help="USPS state acronym (required unless --all-states)",
    ),
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
        if state is not None:
            emit(
                {
                    "status": "error",
                    "detail": "Do not pass --state with --all-states",
                },
                human=human,
            )
            raise typer.Exit(code=1)
        body: dict = {"list_types": ["NDZ", "Email", "Phone"]}
        path = "/ops/drop/hash-index-refresh/enqueue-all"
    else:
        if not state:
            emit(
                {
                    "status": "error",
                    "detail": "Pass --state XX or --all-states "
                    "(no implicit CA default)",
                },
                human=human,
            )
            raise typer.Exit(code=1)
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


def _post_spine(
    path: str,
    *,
    execute: bool,
    human: bool,
    body: dict | None = None,
) -> None:
    """POST a DROP spine mutation; dry-run unless --execute."""
    if not execute:
        if body is None:
            emit({"dry_run": True, "would_post": path}, human=human)
        else:
            emit({"dry_run": True, "would_post": body, "path": path}, human=human)
        return
    try:
        kwargs = {} if body is None else {"json_body": body}
        payload = admin_api_request("POST", path, **kwargs)
    except AdminApiError as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc
    emit(payload, human=human)


def _optional_body(**fields: object) -> dict:
    """Build a JSON body from CLI options, omitting unset values."""
    return {key: value for key, value in fields.items() if value is not None}


@app.command("download")
def download(
    execute: bool = typer.Option(False, "--execute"),
    human: bool = typer.Option(False, "--human"),
):
    """Proxy DROP connector download via admin-api."""
    _post_spine("/ops/drop/download", execute=execute, human=human)


@app.command("land")
def land(
    land_attempt_id: int | None = typer.Option(None, "--land-attempt-id"),
    gcs_uri: str | None = typer.Option(None, "--gcs-uri"),
    zip_path: str | None = typer.Option(None, "--zip-path"),
    source_csv_filename: str | None = typer.Option(None, "--source-csv-filename"),
    list_type: str | None = typer.Option(None, "--list-type"),
    execute: bool = typer.Option(False, "--execute"),
    human: bool = typer.Option(False, "--human"),
):
    """Proxy DROP ingestor land via admin-api (optional LandProxyBody fields)."""
    body = _optional_body(
        land_attempt_id=land_attempt_id,
        gcs_uri=gcs_uri,
        zip_path=zip_path,
        source_csv_filename=source_csv_filename,
        list_type=list_type,
    )
    _post_spine("/ops/drop/land", execute=execute, human=human, body=body)


@app.command("promote")
def promote(
    promote_attempt_id: int | None = typer.Option(None, "--promote-attempt-id"),
    source_csv_filename: str | None = typer.Option(None, "--source-csv-filename"),
    list_type: str | None = typer.Option(None, "--list-type"),
    limit: int | None = typer.Option(None, "--limit", min=1, max=5000),
    execute: bool = typer.Option(False, "--execute"),
    human: bool = typer.Option(False, "--human"),
):
    """Proxy DROP ingestor promote via admin-api (optional PromoteProxyBody fields)."""
    body = _optional_body(
        promote_attempt_id=promote_attempt_id,
        source_csv_filename=source_csv_filename,
        list_type=list_type,
        limit=limit,
    )
    _post_spine("/ops/drop/promote", execute=execute, human=human, body=body)


@app.command("dispatch")
def dispatch(
    limit: int | None = typer.Option(None, "--limit", min=1, max=5000),
    drain_all: bool = typer.Option(False, "--drain-all"),
    execute: bool = typer.Option(False, "--execute"),
    human: bool = typer.Option(False, "--human"),
):
    """Proxy request dispatcher via admin-api (optional DispatchProxyBody fields)."""
    body = _optional_body(limit=limit)
    if drain_all:
        body["drain_all"] = True
    _post_spine("/ops/drop/dispatch", execute=execute, human=human, body=body)


@app.command("match")
def match(
    execute: bool = typer.Option(False, "--execute"),
    human: bool = typer.Option(False, "--human"),
):
    """Kick matching worker process via admin-api."""
    _post_spine("/ops/drop/match", execute=execute, human=human)


@app.command("backfill-matching-stats")
def backfill_matching_stats(
    process_id: int = typer.Option(..., "--process-id", min=1),
    execute: bool = typer.Option(False, "--execute"),
    human: bool = typer.Option(False, "--human"),
):
    """One-shot matching rollup backfill for one download process_id (minutes)."""
    path = f"/ops/drop/processes/{process_id}/backfill-matching-stats"
    if not execute:
        emit({"dry_run": True, "would_post": path}, human=human)
        return
    try:
        payload = admin_api_request("POST", path, timeout=3300.0)
    except AdminApiError as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc
    emit(payload, human=human)


@app.command("fulfill")
def fulfill(
    request_id: str | None = typer.Option(None, "--request-id"),
    limit: int | None = typer.Option(None, "--limit", min=1, max=5000),
    execute: bool = typer.Option(False, "--execute"),
    human: bool = typer.Option(False, "--human"),
):
    """Proxy data fulfillment via admin-api (optional FulfillProxyBody fields)."""
    body = _optional_body(request_id=request_id, limit=limit)
    _post_spine("/ops/drop/fulfill", execute=execute, human=human, body=body)
