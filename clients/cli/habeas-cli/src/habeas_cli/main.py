"""Habeas CLI — mutations via admin-api; reads via read-only Postgres."""

import typer

from habeas_cli.commands import audit, auth, db, drop, queue, request, stats, worker

app = typer.Typer(help="Habeas privacy automation command-line interface")
app.add_typer(db.app, name="db")
app.add_typer(request.app, name="request")
app.add_typer(queue.app, name="queue")
app.add_typer(worker.app, name="worker")
app.add_typer(audit.app, name="audit")
app.add_typer(drop.app, name="drop")
app.add_typer(auth.app, name="auth")
app.add_typer(stats.app, name="stats")


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
                "stats match-quality",
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
                "drop pipeline",
                "drop download",
                "drop land",
                "drop promote",
                "drop dispatch",
                "drop match",
                "drop fulfill",
                "drop hash-index-refresh enqueue|process|status",
                "auth login [--adc]",
                "auth logout",
                "auth status",
            ]
        },
        human=human,
    )


if __name__ == "__main__":
    app()
