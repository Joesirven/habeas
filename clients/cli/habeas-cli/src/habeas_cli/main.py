"""Habeas CLI — mutations via admin-api; reads via read-only Postgres."""

import typer

from habeas_cli.commands import audit, db, queue, request, worker

app = typer.Typer(help="Habeas privacy automation command-line interface")
app.add_typer(db.app, name="db")
app.add_typer(request.app, name="request")
app.add_typer(queue.app, name="queue")
app.add_typer(worker.app, name="worker")
app.add_typer(audit.app, name="audit")


@app.callback()
def main():
    """Hybrid client: writes through admin-api; analysis reads via read-only database role."""


@app.command("version")
def version():
    """Print CLI version."""
    typer.echo("habeas-cli 0.1.0")


@app.command("commands")
def commands(human: bool = typer.Option(False, "--human")):
    """List available subcommands for agents."""
    from habeas_cli.output import emit

    emit(
        {
            "commands": [
                "db tables",
                "db describe TABLE",
                "db query SQL",
                "request show ID",
                "request list",
                "request status ID",
                "queue pending",
                "queue in-flight",
                "queue stuck",
                "queue recent-errors",
                "worker status",
                "worker logs",
                "audit recent",
                "audit for COMMAND",
                "audit by-actor ACTOR",
            ]
        },
        human=human,
    )


if __name__ == "__main__":
    app()
