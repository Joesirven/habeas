"""Live Paylocity connection test via client-credentials token exchange.

Production token host: ``api.paylocity.com``.
Sandbox token host: ``dc1demogw.paylocity.com`` (Paylocity WebLink sandbox gateway).
"""

from __future__ import annotations

from admin_api.connection_tests import _http

_SYSTEM = "paylocity"

_TOKEN_PATH = "/IdentityServer/connect/token"
_PRODUCTION_TOKEN_URL = f"https://api.paylocity.com{_TOKEN_PATH}"
_SANDBOX_TOKEN_URL = f"https://dc1demogw.paylocity.com{_TOKEN_PATH}"


def _token_url(environment: str) -> str | None:
    normalized = environment.strip().casefold()
    if normalized == "production":
        return _PRODUCTION_TOKEN_URL
    if normalized == "sandbox":
        return _SANDBOX_TOKEN_URL
    return None


def _detail_from_status(status: int | None) -> tuple[bool, str]:
    if status is None:
        return False, "unreachable"
    if status == 200:
        return True, "paylocity_ok"
    if status in (401, 403):
        return False, "auth_failed"
    if 400 <= status < 500:
        return False, "invalid_credentials"
    return False, "unknown_error"


async def test_paylocity(credentials: dict[str, str]) -> tuple[bool, str]:
    token_url = _token_url(credentials["environment"])
    if token_url is None:
        return False, "invalid_config"

    status, _ = await _http.request(
        system=_SYSTEM,
        method="POST",
        url=token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
            "scope": "WebLinkAPI",
        },
    )
    return _detail_from_status(status)


# Not a pytest test — called by connection_testers dispatcher.
test_paylocity.__test__ = False
