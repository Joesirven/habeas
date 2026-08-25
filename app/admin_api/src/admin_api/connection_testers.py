"""Connection testers for integration onboarding.

Per-system live HTTP checks live under ``connection_tests/``; callers should
keep using ``test_connection`` as the single entry point.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import httpx

from admin_api.connection_tests import auth0, google_sheets, lever, paylocity, upload_csv
from habeas_privacy_core.connections.models import sanitize_test_detail
from habeas_privacy_core.connections.systems import get_system, validate_credentials

logger = logging.getLogger(__name__)

_SystemTester = Callable[[dict[str, str]], Awaitable[tuple[bool, str]]]

_SYSTEM_TESTERS: dict[str, _SystemTester] = {
    "paylocity": paylocity.test_paylocity,
    "lever": lever.test_lever,
    "auth0": auth0.test_auth0,
    "google_sheets": google_sheets.test_google_sheets,
}


async def test_connection(
    system: str,
    credentials: dict[str, str],
    *,
    impersonate_service_account: str | None = None,
) -> tuple[bool, str]:
    """Run a connection test for *system* using owner-submitted *credentials*.

    Returns ``(ok, detail)`` where *detail* is an allowlisted short code only.
    Credential values are never logged.
    """
    logger.info("connection_test_started system=%s", system)

    try:
        system_def = get_system(system)
    except ValueError:
        logger.info("connection_test_finished system=%s ok=false detail=unknown_system", system)
        return False, "unknown_system"

    if system == "cassandra":
        logger.info("connection_test_finished system=%s ok=false detail=infra_only", system)
        return False, "infra_only"

    tester = _SYSTEM_TESTERS.get(system)
    if tester is None:
        logger.info("connection_test_finished system=%s ok=false detail=unknown_system", system)
        return False, "unknown_system"

    try:
        validated = validate_credentials(system_def, credentials)
    except ValueError:
        logger.info(
            "connection_test_finished system=%s ok=false detail=missing_credentials",
            system,
        )
        return False, "missing_credentials"

    try:
        if system == "google_sheets":
            ok, detail = await google_sheets.test_google_sheets(
                validated,
                impersonate_email=impersonate_service_account,
            )
        else:
            ok, detail = await tester(validated)
    except httpx.RequestError:
        logger.info("connection_test_finished system=%s ok=false detail=unreachable", system)
        return False, "unreachable"
    except Exception:
        logger.info("connection_test_finished system=%s ok=false detail=unknown_error", system)
        return False, "unknown_error"

    safe_detail = sanitize_test_detail(detail) or "unknown_error"
    logger.info(
        "connection_test_finished system=%s ok=%s detail=%s",
        system,
        ok,
        safe_detail,
    )
    return ok, safe_detail


# Not a pytest test — public API for connection onboarding routes.
test_connection.__test__ = False


async def test_upload_connection(
    system: str,
    *,
    content: bytes,
    multi_pii_delimiter: str | None,
    column_mapping: dict[str, str] | None = None,
    email_format: str | None = None,
    phone_format: str | None = None,
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
            email_format=email_format,
            phone_format=phone_format,
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
