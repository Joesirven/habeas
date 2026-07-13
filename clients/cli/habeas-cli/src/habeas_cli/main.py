"""Habeas CLI — mutations via admin-api; reads via database (future)."""

import typer

app = typer.Typer(help="Habeas privacy automation command-line interface")


@app.callback()
def main():
    """Hybrid client: writes through admin-api; analysis reads via read-only database role."""


@app.command("version")
def version():
    """Print CLI version."""
    typer.echo("habeas-cli 0.1.0")


if __name__ == "__main__":
    app()
