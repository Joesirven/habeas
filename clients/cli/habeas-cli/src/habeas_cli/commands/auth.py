"""CLI auth login / logout / status for admin-api (IAP or ADC)."""

from __future__ import annotations

import os

import typer

from habeas_cli.admin_api_client import (
    AdminApiError,
    admin_api_base_url,
    cloud_run_audience,
    expires_at_iso_from_token,
    fetch_adc_id_token,
    fetch_iap_id_token,
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


def _require_iap_client_id() -> str:
    client_id = os.environ.get("IAP_OAUTH_CLIENT_ID", "").strip()
    if not client_id:
        raise typer.BadParameter(
            "IAP_OAUTH_CLIENT_ID is required for `auth login` (IAP path). "
            "Set it to the IAP OAuth client id for admin-api, or use "
            "`habeas-cli auth login --adc` for the super_admin ADC path."
        )
    return client_id


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

    Default: IAP audience token + email bound to the active gcloud account.
    ``--adc``: verify ADC can mint a Cloud Run ID token and store ADC mode.
    """
    base_url = admin_api_base_url()
    try:
        email = gcloud_active_account()
    except AdminApiError as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc

    if adc:
        try:
            audience = cloud_run_audience(base_url)
            token = fetch_adc_id_token(audience)
        except (AdminApiError, ValueError) as exc:
            emit({"status": "error", "detail": str(exc)}, human=human)
            raise typer.Exit(code=1) from exc
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

    try:
        client_id = _require_iap_client_id()
    except typer.BadParameter as exc:
        emit({"status": "error", "detail": str(exc)}, human=human)
        raise typer.Exit(code=1) from exc

    try:
        token = fetch_iap_id_token(client_id)
    except AdminApiError as exc:
        emit(
            {
                "status": "error",
                "detail": (
                    f"IAP mint failed: {exc}. Check IAP_OAUTH_CLIENT_ID, "
                    "TokenCreator on IAP_IMPERSONATE_SERVICE_ACCOUNT, and "
                    "IAP accessor grants."
                ),
            },
            human=human,
        )
        raise typer.Exit(code=1) from exc

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
