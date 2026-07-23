"""CLI auth login / logout / status for admin-api (IAP or ADC)."""

from __future__ import annotations

import typer

from habeas_cli.admin_api_client import (
    AdminApiError,
    admin_api_base_url,
    cloud_run_audience,
    expires_at_iso_from_token,
    fetch_adc_id_token,
    gcloud_active_account,
)
from habeas_cli.credentials import (
    clear_credentials,
    credentials_path,
    credentials_status_public,
    load_credentials,
    save_credentials,
)
from habeas_cli.output import emit

app = typer.Typer(help="Authenticate the CLI against admin-api (IAP or ADC)")


@app.command("login")
def login(
    adc: bool = typer.Option(
        False,
        "--adc",
        help="Use ADC Cloud Run ID token (super_admin path); no IAP email header",
    ),
    human: bool = typer.Option(False, "--human", help="Pretty-print JSON"),
) -> None:
    """Mint and store credentials for admin-api mutations.

    Default (allowlisted roles): Cloud Run ID token (ADC, audience = service URL)
    plus ``X-Goog-Authenticated-User-Email`` bound to the active gcloud account.
    ``--adc``: same token mint, no email header (super_admin Bearer-only path).

    admin-api-dev runs with Cloud Run IAP off; service-URL audience is required
    for IAM invoker. Legacy IAP OAuth-client audiences are not used here.
    """
    base_url = admin_api_base_url()
    try:
        email = gcloud_active_account()
    except AdminApiError as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc

    try:
        audience = cloud_run_audience(base_url)
        token = fetch_adc_id_token(audience)
    except (AdminApiError, ValueError) as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc

    if adc:
        path = save_credentials(
            {
                "auth": "adc",
                "email": email,
                "id_token": token,
                "expires_at": expires_at_iso_from_token(token),
                "admin_api_url": base_url,
            }
        )
        emit(
            {
                "ok": True,
                "auth": "adc",
                "email": email,
                "expires_at": expires_at_iso_from_token(token),
                "admin_api_url": base_url,
                "credentials_path": str(path),
            },
            human=human,
        )
        return

    path = save_credentials(
        {
            "auth": "iap",
            "email": email,
            "iap_id_token": token,
            "expires_at": expires_at_iso_from_token(token),
            "admin_api_url": base_url,
        }
    )
    emit(
        {
            "ok": True,
            "auth": "iap",
            "email": email,
            "expires_at": expires_at_iso_from_token(token),
            "admin_api_url": base_url,
            "credentials_path": str(path),
        },
        human=human,
    )


@app.command("logout")
def logout(
    human: bool = typer.Option(False, "--human", help="Pretty-print JSON"),
) -> None:
    """Remove stored admin-api credentials."""
    removed = clear_credentials()
    emit(
        {
            "ok": True,
            "removed": removed,
            "credentials_path": str(credentials_path()),
        },
        human=human,
    )


@app.command("status")
def status(
    human: bool = typer.Option(False, "--human", help="Pretty-print JSON"),
) -> None:
    """Show auth mode, email, and token expiry — never prints secrets."""
    try:
        data = load_credentials()
    except Exception as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc
    public = credentials_status_public(data)
    public["credentials_path"] = str(credentials_path())
    public["admin_api_url_env"] = admin_api_base_url()
    emit(public, human=human)
