"""Stub connection testers for integration onboarding.

Live vendor HTTP checks can replace the stub path per system later; callers
should keep using ``test_connection`` as the single entry point.
"""

from __future__ import annotations

import logging

from habeas_privacy_core.connections.systems import get_system, validate_credentials

logger = logging.getLogger(__name__)

_SAAS_SYSTEMS = frozenset({"mailchimp", "paylocity", "lever", "auth0", "google_sheets"})


async def test_connection(system: str, credentials: dict[str, str]) -> tuple[bool, str]:
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

    if system not in _SAAS_SYSTEMS:
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

    # Future: dispatch to per-system live HTTP testers (e.g. Mailchimp ping).
    _ = validated
    logger.info("connection_test_finished system=%s ok=true detail=stub_ok", system)
    return True, "stub_ok"


# Not a pytest test — public API for connection onboarding routes.
test_connection.__test__ = False
