"""Worker inspection commands (GCP stubs at MVP)."""

import typer

from habeas_cli.output import emit

app = typer.Typer(help="Cloud Run worker status")


@app.command("status")
def worker_status(
    human: bool = typer.Option(False, "--human"),
):
    emit(
        {
            "workers": [],
            "note": "Cloud Run status requires gcloud integration — deferred to post-T3.5",
        },
        human=human,
    )


@app.command("logs")
def worker_logs(
    human: bool = typer.Option(False, "--human"),
):
    emit(
        {
            "logs": [],
            "note": "Cloud Logging tail requires gcloud integration — deferred to post-T3.5",
        },
        human=human,
    )
