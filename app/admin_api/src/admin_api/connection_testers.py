"""Connection testers for integration onboarding.

Per-system live checks live under ``connection_tests/``; callers should
keep using ``test_connection`` as the single entry point.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from admin_api.connection_tests import auth0, google_sheets, lever, mailchimp, paylocity, upload_csv
from habeas_privacy_core.connections.models import sanitize_test_detail
from habeas_privacy_core.connections.systems import get_system, validate_credentials

logger = logging.getLogger(__name__)

_SystemTester = Callable[..., Awaitable[tuple]]

_SYSTEM_TESTERS: dict[str, _SystemTester] = {
    "mailchimp": mailchimp.test_mailchimp,
    "paylocity": paylocity.test_paylocity,
    "lever": lever.test_lever,
    "auth0": auth0.test_auth0,
    "google_sheets": google_sheets.test_google_sheets,
}

_TRIAGE_ALLOWLIST_KEYS = frozenset(
    {"step", "status_code", "status_class", "error_kind", "detail", "port"}
)


def sanitize_triage(triage: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only allowlisted non-secret triage fields."""
    if not triage:
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in triage.items():
        if key not in _TRIAGE_ALLOWLIST_KEYS:
            continue
        if key == "detail" and isinstance(value, str):
            cleaned[key] = sanitize_test_detail(value) or "unknown_error"
        elif key == "status_code" and isinstance(value, int) and 100 <= value <= 599:
            cleaned[key] = value
        elif key == "status_class" and isinstance(value, str) and value in {
            "1xx",
            "2xx",
            "3xx",
            "4xx",
            "5xx",
        }:
            cleaned[key] = value
        elif key == "step" and isinstance(value, str) and value.isidentifier():
            cleaned[key] = value
        elif key == "error_kind" and isinstance(value, str) and value.replace("_", "").isalnum():
            cleaned[key] = value[:64]
        elif key == "port" and isinstance(value, int) and 1 <= value <= 65535:
            cleaned[key] = value
    return cleaned


def _normalize_tester_result(result: tuple) -> tuple[bool, str, dict[str, Any]]:
    if len(result) == 3:
        ok, detail, triage = result
        return bool(ok), str(detail), sanitize_triage(triage if isinstance(triage, dict) else {})
    if len(result) == 2:
        ok, detail = result
        return bool(ok), str(detail), {}
    return bool(result), "ok" if result else "failed", {}


async def test_connection(
    system: str,
    credentials: dict[str, str],
    *,
    impersonate_service_account: str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Run a connection test for *system* using owner-submitted *credentials*.

    Returns ``(ok, detail, triage)`` where *detail* is an allowlisted short code
    and *triage* holds safe structured fields (step / status class / error kind).
    Credential values are never logged.
    """
    logger.info("connection_test_started system=%s", system)

    try:
        system_def = get_system(system)
    except ValueError:
        logger.info("connection_test_finished system=%s ok=false detail=unknown_system", system)
        return False, "unknown_system", {"detail": "unknown_system"}

    if system == "cassandra":
        logger.info("connection_test_finished system=%s ok=false detail=infra_only", system)
        return False, "infra_only", {"detail": "infra_only"}

    tester = _SYSTEM_TESTERS.get(system)
    if tester is None:
        logger.info("connection_test_finished system=%s ok=false detail=unknown_system", system)
        return False, "unknown_system", {"detail": "unknown_system"}

    try:
        validated = validate_credentials(system_def, credentials)
    except ValueError:
        logger.info(
            "connection_test_finished system=%s ok=false detail=missing_credentials",
            system,
        )
        return False, "missing_credentials", {"detail": "missing_credentials"}

    try:
        if system == "google_sheets":
            raw = await google_sheets.test_google_sheets(
                validated,
                impersonate_email=impersonate_service_account,
            )
        else:
            raw = await tester(validated)
        ok, detail, triage = _normalize_tester_result(raw)
    except httpx.TimeoutException:
        logger.info(
            "connection_test_finished system=%s ok=false detail=timeout error_kind=timeout",
            system,
        )
        return False, "timeout", {"detail": "timeout", "error_kind": "timeout"}
    except httpx.RequestError:
        logger.info(
            "connection_test_finished system=%s ok=false detail=unreachable error_kind=connect_error",
            system,
        )
        return False, "unreachable", {"detail": "unreachable", "error_kind": "connect_error"}
    except Exception:
        logger.info("connection_test_finished system=%s ok=false detail=unknown_error", system)
        return False, "unknown_error", {"detail": "unknown_error"}

    safe_detail = sanitize_test_detail(detail) or "unknown_error"
    triage = sanitize_triage({**triage, "detail": safe_detail})
    logger.info(
        "connection_test_finished system=%s ok=%s detail=%s step=%s status_class=%s error_kind=%s status_code=%s",
        system,
        ok,
        safe_detail,
        triage.get("step"),
        triage.get("status_class"),
        triage.get("error_kind"),
        triage.get("status_code"),
    )
    return ok, safe_detail, triage


# Not a pytest test — public API for connection onboarding routes.
test_connection.__test__ = False


async def test_upload_connection(
    system: str,
    *,
    content: bytes,
    multi_pii_delimiter: str | None,
    column_mapping: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Run an upload CSV connection test without Live credential validation."""
    logger.info("connection_test_started system=%s mode=upload", system)

    if system not in upload_csv.UPLOAD_SYSTEMS:
        logger.info(
            "connection_test_finished system=%s ok=false detail=unknown_system",
            system,
        )
        return False, "unknown_system"

    try:
        ok, detail, _stats = await upload_csv.test_upload_system(
            system,
            content=content,
            multi_pii_delimiter=multi_pii_delimiter,
            column_mapping=column_mapping,
        )
    except Exception:
        logger.info(
            "connection_test_finished system=%s ok=false detail=unknown_error",
            system,
        )
        return False, "unknown_error"

    safe_detail = sanitize_test_detail(detail) or "unknown_error"
    logger.info(
        "connection_test_finished system=%s ok=%s detail=%s",
        system,
        ok,
        safe_detail,
    )
    return ok, safe_detail


# Not a pytest test — public API for upload onboarding routes.
test_upload_connection.__test__ = False
