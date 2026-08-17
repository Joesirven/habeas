"""Live Lever connection test."""

from __future__ import annotations

from admin_api.connection_tests import _http

_SYSTEM = "lever"
_LEVER_USERS_URL = "https://api.lever.co/v1/users?limit=1"
_STEP = "users_get"


async def test_lever(credentials: dict[str, str]) -> tuple[bool, str, dict]:
    api_key = credentials["api_key"]

    probe = await _http.request(
        system=_SYSTEM,
        method="GET",
        url=_LEVER_USERS_URL,
        step=_STEP,
        auth=(api_key, ""),
    )
    ok, detail = _http.classify_http_result(probe, success_detail="lever_ok")
    triage = probe.triage()
    triage["detail"] = detail
    return ok, detail, triage


# Not a pytest test — public API for connection onboarding routes.
test_lever.__test__ = False
