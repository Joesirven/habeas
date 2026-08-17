"""Live Mailchimp connection test."""

from __future__ import annotations

import re

from admin_api.connection_tests import _http

_SYSTEM = "mailchimp"
_DC_SUFFIX_RE = re.compile(r"^[a-z0-9]+$", re.IGNORECASE)
_STEP = "root_get"


def _parse_datacenter(api_key: str) -> str | None:
    if "-" not in api_key:
        return None
    datacenter = api_key.rsplit("-", 1)[-1]
    if not datacenter or not _DC_SUFFIX_RE.match(datacenter):
        return None
    return datacenter.lower()


async def test_mailchimp(credentials: dict[str, str]) -> tuple[bool, str, dict]:
    api_key = credentials["api_key"]
    datacenter = _parse_datacenter(api_key)
    if datacenter is None:
        return False, "invalid_config", {"step": "parse_datacenter", "detail": "invalid_config"}

    probe = await _http.request(
        system=_SYSTEM,
        method="GET",
        url=f"https://{datacenter}.api.mailchimp.com/3.0/",
        step=_STEP,
        auth=("anystring", api_key),
    )
    ok, detail = _http.classify_http_result(probe, success_detail="mailchimp_ok")
    triage = probe.triage()
    triage["detail"] = detail
    return ok, detail, triage


# Not a pytest test — public API for connection onboarding.
test_mailchimp.__test__ = False
