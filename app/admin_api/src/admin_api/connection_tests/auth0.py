"""Live Auth0 connection test via Management API client-credentials token."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from admin_api.connection_tests import _http

_SYSTEM = "auth0"
_STEP = "oauth_token"
_HOSTNAME_RE = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)


def _normalize_domain(domain: str) -> str | None:
    """Return hostname only, or None when the tenant domain is unusable."""
    value = domain.strip()
    if not value:
        return None

    if "://" in value:
        parsed = urlparse(value)
        host = parsed.hostname
        if not host:
            return None
        value = host
    else:
        value = value.split("/", 1)[0]
        value = value.split(":", 1)[0]

    value = value.rstrip(".").lower()
    if not value or "." not in value or not _HOSTNAME_RE.match(value):
        return None
    return value


async def test_auth0(credentials: dict[str, str]) -> tuple[bool, str, dict]:
    domain = _normalize_domain(credentials["domain"])
    if domain is None:
        return False, "invalid_config", {"step": "normalize_domain", "detail": "invalid_config"}

    probe = await _http.request(
        system=_SYSTEM,
        method="POST",
        url=f"https://{domain}/oauth/token",
        step=_STEP,
        json={
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
            "audience": f"https://{domain}/api/v2/",
            "grant_type": "client_credentials",
        },
    )
    ok, detail = _http.classify_http_result(probe, success_detail="auth0_ok")
    triage = probe.triage()
    triage["detail"] = detail
    return ok, detail, triage


# Not a pytest test — invoked by connection_testers only.
test_auth0.__test__ = False
