"""Super-admin lab API for the first CA DROP production pull.

Stores the production API key in Secret Manager (``drop-prod-api-key``).
Confirm-run proxies the existing spine: download → land → promote →
dispatch → ensure-drain. Does not start fulfillment, upload/amend DROP,
or touch Cassandra.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.drop_pipeline import (
    DISPATCH_PROXY_TIMEOUT,
    DOWNLOAD_PROXY_TIMEOUT,
    LAND_PROXY_TIMEOUT,
    MATCHING_DRAIN_PROXY_TIMEOUT,
    PROMOTE_PROXY_TIMEOUT,
    get_pipeline_status,
    proxy_post_payload,
    settings as drop_settings,
)
from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.audit.writer import write_audit
from habeas_privacy_core.auth import ROLE_SUPER_ADMIN
from habeas_privacy_core.config import CoreSettings

logger = logging.getLogger(__name__)

DROP_PROD_API_KEY_SECRET_ID = "drop-prod-api-key"

router = APIRouter(prefix="/ops/drop/prod", tags=["drop-prod-cutover"])

SuperAdminPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN)),
]

CONFIRM_RUN_STEPS: tuple[str, ...] = (
    "download",
    "land",
    "promote",
    "dispatch",
    "ensure-drain",
)

# Download queues one land per list (Email / Phone / NDZ) and returns those ids.
# Land those ids only (never FIFO-claim leftovers). Promote and dispatch are
# one call each — promote drains internally; dispatch uses DISPATCH_PROXY_TIMEOUT.
# Promote limit is the ingest batch size. Dispatch sends drain_all plus a large
# limit so the worker uses fewer internal ticks (DispatchRequest.limit max 2_000_000).
PROMOTE_CONFIRM_LIMIT = 5000
DISPATCH_CONFIRM_LIMIT = 50_000


class DropProdCutoverSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = DropProdCutoverSettings()

# Injectable Secret Manager client for tests. Production uses GSM.
_gsm_client: Any | None = None

_last_run: dict[str, Any] = {
    "process_id": None,
    "run_id": None,
}


class StoreKeyBody(BaseModel):
    api_key: str = Field(min_length=1)


class ConfirmRunBody(BaseModel):
    confirm: Literal[True]


class StoreKeyResponse(BaseModel):
    status: str
    configured: bool


class ConfirmRunResponse(BaseModel):
    status: str
    process_id: int | None = None
    run_id: str | None = None


def set_gsm_client(client: Any | None) -> None:
    """Override the Secret Manager client (tests)."""
    global _gsm_client
    _gsm_client = client


def clear_last_run_for_tests() -> None:
    _last_run["process_id"] = None
    _last_run["run_id"] = None


def _gcp_project_id() -> str:
    project = (settings.gcp_project or "").strip()
    if project:
        return project
    return (
        os.environ.get("GCP_PROJECT", "").strip()
        or os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        or "example-gcp-project"
    )


def _gsm_client_or_create() -> Any:
    if _gsm_client is not None:
        return _gsm_client
    try:
        from google.cloud import secretmanager  # type: ignore[import-untyped]
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="secret_manager_unavailable",
        ) from exc
    return secretmanager.SecretManagerServiceClient()


def _is_already_exists(exc: BaseException) -> bool:
    return type(exc).__name__ == "AlreadyExists"


def _is_not_found(exc: BaseException) -> bool:
    return type(exc).__name__ == "NotFound"


def _secret_parent(*, project_id: str) -> str:
    return f"projects/{project_id}"


def _secret_resource(*, project_id: str) -> str:
    return f"{_secret_parent(project_id=project_id)}/secrets/{DROP_PROD_API_KEY_SECRET_ID}"


def put_drop_prod_api_key(value: str) -> None:
    """Persist the prod key in GSM. Never log the value."""
    client = _gsm_client_or_create()
    project_id = _gcp_project_id()
    parent = _secret_parent(project_id=project_id)
    try:
        client.create_secret(
            request={
                "parent": parent,
                "secret_id": DROP_PROD_API_KEY_SECRET_ID,
                "secret": {"replication": {"automatic": {}}},
            }
        )
    except Exception as exc:
        if not _is_already_exists(exc):
            logger.warning(
                "drop_prod_secret_create_failed",
                extra={
                    "event": "drop_prod_secret_create_failed",
                    "error_type": type(exc).__name__,
                    "secret_id": DROP_PROD_API_KEY_SECRET_ID,
                },
            )
            raise HTTPException(status_code=502, detail="secret_write_failed") from exc
    try:
        client.add_secret_version(
            request={
                "parent": _secret_resource(project_id=project_id),
                "payload": {"data": value.encode("utf-8")},
            }
        )
    except Exception as exc:
        logger.warning(
            "drop_prod_secret_version_failed",
            extra={
                "event": "drop_prod_secret_version_failed",
                "error_type": type(exc).__name__,
                "secret_id": DROP_PROD_API_KEY_SECRET_ID,
            },
        )
        raise HTTPException(status_code=502, detail="secret_write_failed") from exc


def drop_prod_api_key_configured() -> bool:
    """True when GSM has an enabled latest version. Never loads payload.data."""
    client = _gsm_client_or_create()
    name = f"{_secret_resource(project_id=_gcp_project_id())}/versions/latest"
    try:
        client.get_secret_version(request={"name": name})
    except Exception as exc:
        if _is_not_found(exc):
            return False
        logger.warning(
            "drop_prod_secret_lookup_failed",
            extra={
                "event": "drop_prod_secret_lookup_failed",
                "error_type": type(exc).__name__,
                "secret_id": DROP_PROD_API_KEY_SECRET_ID,
            },
        )
        return False
    return True


async def _audit(*, actor: str, command: str, result_status: int, result_summary: str) -> None:
    """Audit command name + actor only. Never include the secret."""
    try:
        await write_audit(
            actor=actor,
            interface="admin-api",
            command=command,
            arguments={},
            result_status=result_status,
            result_summary=result_summary,
        )
    except Exception:
        logger.warning(
            "drop_prod_cutover_audit_failed",
            extra={"event": "drop_prod_cutover_audit_failed", "command": command},
        )


def _process_id_from_download(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("connector_attempt_id", "process_id", "attempt_id"):
        raw = payload.get(key)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
    return None


def _land_attempt_ids_from_download(payload: Any) -> list[int]:
    """Ints only. Ignore junk. Never log filenames / lists / URIs."""
    if not isinstance(payload, dict):
        return []
    raw = payload.get("land_attempt_ids")
    if not isinstance(raw, list):
        return []
    ids: list[int] = []
    for item in raw:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            ids.append(item)
    return ids


def _step_url(step: str) -> tuple[str, float]:
    connector = drop_settings.drop_connector_url.rstrip("/")
    ingestor = drop_settings.drop_ingestor_url.rstrip("/")
    dispatcher = drop_settings.request_dispatcher_url.rstrip("/")
    matching = drop_settings.matching_url.rstrip("/")
    mapping: dict[str, tuple[str, float]] = {
        "download": (f"{connector}/download", DOWNLOAD_PROXY_TIMEOUT),
        "land": (f"{ingestor}/ingest/land", LAND_PROXY_TIMEOUT),
        "promote": (f"{ingestor}/ingest/promote", PROMOTE_PROXY_TIMEOUT),
        "dispatch": (f"{dispatcher}/dispatch", DISPATCH_PROXY_TIMEOUT),
        "ensure-drain": (f"{matching}/ensure-drain", MATCHING_DRAIN_PROXY_TIMEOUT),
    }
    return mapping[step]


def _worker_status(payload: Any) -> str | None:
    if isinstance(payload, dict):
        raw = payload.get("status")
        if isinstance(raw, str):
            return raw
    return None


def _download_uri_scheme(payload: Any) -> str | None:
    """Scheme only. Never return the URI (ZIP path / object name)."""
    if not isinstance(payload, dict):
        return None
    uri = payload.get("gcs_uri")
    if not isinstance(uri, str) or not uri.strip():
        return None
    return uri.split(":", 1)[0]


def _log_confirm_step_failed(
    step: str,
    *,
    status_code: int | None = None,
    reason: str | None = None,
    gcs_uri_scheme: str | None = None,
) -> None:
    extra: dict[str, Any] = {
        "event": "drop_prod_confirm_step_failed",
        "step": step,
    }
    if status_code is not None:
        extra["status_code"] = status_code
    if reason is not None:
        extra["reason"] = reason
    if gcs_uri_scheme is not None:
        extra["gcs_uri_scheme"] = gcs_uri_scheme
    logger.warning("drop_prod_confirm_step_failed", extra=extra)


async def _proxy_confirm_step(
    step: str,
    json_body: dict[str, Any],
) -> tuple[int, Any]:
    url, timeout = _step_url(step)
    return await proxy_post_payload(url, json_body=json_body, timeout=timeout)


def _download_uri_is_landable(payload: Any) -> bool:
    """Land cannot read another Cloud Run's /tmp. Reject missing or file://."""
    scheme = _download_uri_scheme(payload)
    if scheme is None or scheme.lower() == "file":
        _log_confirm_step_failed(
            "download",
            reason="unreadable_uri",
            gcs_uri_scheme=scheme if scheme is not None else "missing",
        )
        return False
    logger.info(
        "drop_prod_confirm_download_uri",
        extra={
            "event": "drop_prod_confirm_download_uri",
            "gcs_uri_scheme": scheme,
        },
    )
    return True


async def _proxy_once_must_work(
    step: str,
    *,
    json_body: dict[str, Any],
) -> bool:
    """POST once. False on non-200 or idle (empty first pull)."""
    status_code, payload = await _proxy_confirm_step(step, json_body)
    if status_code != 200:
        _log_confirm_step_failed(step, status_code=status_code)
        return False
    if _worker_status(payload) == "idle":
        _log_confirm_step_failed(step, reason="first_idle")
        return False
    return True


async def _land_bound_attempts(land_attempt_ids: list[int]) -> bool:
    """Land this download's attempt ids only. Never FIFO-claim leftovers."""
    if not land_attempt_ids:
        _log_confirm_step_failed("land", reason="missing_land_attempt_ids")
        return False
    for attempt_id in land_attempt_ids:
        status_code, payload = await _proxy_confirm_step(
            "land", {"land_attempt_id": attempt_id}
        )
        if status_code != 200:
            _log_confirm_step_failed("land", status_code=status_code)
            return False
        if _worker_status(payload) != "ok":
            _log_confirm_step_failed("land", reason="first_idle")
            return False
    return True


async def _run_confirm_steps() -> tuple[str, int | None]:
    process_id: int | None = None
    land_attempt_ids: list[int] = []
    for step in CONFIRM_RUN_STEPS:
        if step == "download":
            status_code, payload = await _proxy_confirm_step(step, {})
            if status_code != 200:
                _log_confirm_step_failed(step, status_code=status_code)
                return "error", process_id
            process_id = _process_id_from_download(payload)
            if not _download_uri_is_landable(payload):
                return "error", process_id
            land_attempt_ids = _land_attempt_ids_from_download(payload)
            continue
        if step == "land":
            drained = await _land_bound_attempts(land_attempt_ids)
            if not drained:
                return "error", process_id
            continue
        if step == "promote":
            ok = await _proxy_once_must_work(
                step,
                json_body={"limit": PROMOTE_CONFIRM_LIMIT},
            )
            if not ok:
                return "error", process_id
            continue
        if step == "dispatch":
            ok = await _proxy_once_must_work(
                step,
                json_body={
                    "limit": DISPATCH_CONFIRM_LIMIT,
                    "drain_all": True,
                },
            )
            if not ok:
                return "error", process_id
            continue
        if step == "ensure-drain":
            status_code, _payload = await _proxy_confirm_step(step, {})
            if status_code != 200:
                _log_confirm_step_failed(step, status_code=status_code)
                return "error", process_id
            continue
        _log_confirm_step_failed(step, reason="unknown_step")
        return "error", process_id
    return "ok", process_id


@router.post("/key", response_model=StoreKeyResponse)
async def store_drop_prod_api_key(
    body: StoreKeyBody,
    principal: SuperAdminPrincipal,
) -> StoreKeyResponse:
    """Store the CA DROP prod API key in GSM. Never echo the key."""
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=422, detail="api_key required")
    put_drop_prod_api_key(api_key)
    await _audit(
        actor=principal.email,
        command="drop.prod.store_key",
        result_status=200,
        result_summary="key stored",
    )
    return StoreKeyResponse(status="ok", configured=True)


@router.post("/confirm-run", response_model=ConfirmRunResponse)
async def confirm_drop_prod_run(
    body: ConfirmRunBody,
    principal: SuperAdminPrincipal,
) -> ConfirmRunResponse:
    """Download → land → promote → dispatch → ensure-drain. No fulfillment."""
    _ = body
    if not drop_prod_api_key_configured():
        raise HTTPException(status_code=400, detail="key not stored")
    run_id = str(uuid4())
    status, process_id = await _run_confirm_steps()
    _last_run["process_id"] = process_id
    _last_run["run_id"] = run_id
    await _audit(
        actor=principal.email,
        command="drop.prod.confirm_run",
        result_status=200 if status == "ok" else 502,
        result_summary=status,
    )
    return ConfirmRunResponse(status=status, process_id=process_id, run_id=run_id)


@router.get("/status")
async def drop_prod_run_status(_principal: SuperAdminPrincipal) -> dict[str, Any]:
    """Key-configured flag + last run ids + pipeline snapshot (ids/counts)."""
    configured = drop_prod_api_key_configured()
    payload: dict[str, Any] = {
        "status": "ok",
        "configured": configured,
        "process_id": _last_run.get("process_id"),
        "run_id": _last_run.get("run_id"),
    }
    try:
        snapshot = await get_pipeline_status()
    except HTTPException:
        return payload
    except Exception:
        logger.warning(
            "drop_prod_pipeline_status_failed",
            extra={"event": "drop_prod_pipeline_status_failed"},
        )
        return payload
    if isinstance(snapshot, dict):
        for key, value in snapshot.items():
            if key not in payload:
                payload[key] = value
    return payload
