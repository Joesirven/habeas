"""Live Lever connection test."""

from __future__ import annotations

from admin_api.connection_tests import _http

_SYSTEM = "lever"
_LEVER_USERS_URL = "https://api.lever.co/v1/users?limit=1"


async def test_lever(credentials: dict[str, str]) -> tuple[bool, str]:
    api_key = credentials["api_key"]

    status, _ = await _http.request(
        system=_SYSTEM,
        method="GET",
        url=_LEVER_USERS_URL,
        auth=(api_key, ""),
    )

    if status is None:
        return False, "unreachable"
    if status == 200:
        return True, "lever_ok"
    if status in (401, 403):
        return False, "auth_failed"
    if 400 <= status < 500:
        return False, "invalid_credentials"
    return False, "unreachable"


# Not a pytest test — public API for connection onboarding routes.
test_lever.__test__ = False
