"""ManagementExtractAdapter — mocked Management API HTTP."""

from __future__ import annotations

import gzip
import json
import logging
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from auth0.adapters import ManagementApiError, ManagementExtractAdapter
from auth0.adapters.management import ManagementExtractAdapter as DirectAdapter

_DOMAIN = "tenant.us.auth0.com"
_CLIENT_ID = "auth0-client-id"
_CLIENT_SECRET = "auth0-client-secret-value"
_TOKEN = "tok_test_opaque"
_JOB_ID = "job_test0000000001"
# Host pattern from Auth0 bulk-export docs sample location.
_EXPORT_HOST = "pus3-auth0-export-users-us-east-2.s3.us-east-2.amazonaws.com"
# Observed production tenant export host (no "auth0-" label prefix).
_EXPORT_HOST_PROD = "l0-prod-prod-us-1-usw2-export-users.s3.us-west-2.amazonaws.com"
_EXPORT_URL = f"https://{_EXPORT_HOST}/job/{_JOB_ID}/users.json.gz"
_EMAIL_A = "alpha@example.com"
_EMAIL_B = "bravo@example.com"
_EMAIL_C = "charlie@example.com"

_CREDENTIALS = {
    "domain": _DOMAIN,
    "client_id": _CLIENT_ID,
    "client_secret": _CLIENT_SECRET,
}


@dataclass(frozen=True)
class _ObjectCredentials:
    domain: str
    client_id: str
    client_secret: str


def _token_response() -> httpx.Response:
    return httpx.Response(200, json={"access_token": _TOKEN, "token_type": "Bearer"})


def _gzip_ndjson(users: list[dict], *, trailing_blank: bool = True) -> bytes:
    lines = "\n".join(json.dumps(user) for user in users)
    if trailing_blank:
        lines += "\n"
    return gzip.compress(lines.encode("utf-8"))


def _export_handler(
    users: list[dict],
    *,
    polls_before_done: int = 1,
    extra: dict | None = None,
    location: str = _EXPORT_URL,
    summary: dict | None = None,
    export_body: bytes | None = None,
):
    state = {"polls": 0, "paths": [], "hosts": [], "queries": [], "export_auth": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["paths"].append(request.url.path)
        state["hosts"].append(request.url.host or "")
        state["queries"].append(parse_qs(urlparse(str(request.url)).query))
        if extra is not None and extra.get("on_request"):
            override = extra["on_request"](request, state)
            if override is not None:
                return override
        if request.method == "POST" and request.url.path == "/oauth/token":
            return _token_response()
        if request.method == "POST" and request.url.path == "/api/v2/jobs/users-exports":
            body = json.loads(request.content)
            assert body["format"] == "json"
            assert body["fields"] == [{"name": "user_id"}, {"name": "email"}]
            assert "limit" not in body
            return httpx.Response(
                200,
                json={"id": _JOB_ID, "type": "users_export", "status": "pending"},
            )
        if request.method == "GET" and request.url.path == f"/api/v2/jobs/{_JOB_ID}":
            state["polls"] += 1
            if state["polls"] < polls_before_done:
                return httpx.Response(
                    200,
                    json={"id": _JOB_ID, "type": "users_export", "status": "pending"},
                )
            completed: dict = {
                "id": _JOB_ID,
                "type": "users_export",
                "status": "completed",
                "location": location,
            }
            if summary is not None:
                completed["summary"] = summary
            return httpx.Response(200, json=completed)
        if request.url.host == urlparse(location).hostname:
            state["export_auth"].append(request.headers.get("authorization"))
            payload = export_body if export_body is not None else _gzip_ndjson(users)
            return httpx.Response(200, content=payload)
        return httpx.Response(404)

    handler.state = state  # type: ignore[attr-defined]
    return handler


async def _collect(
    handler,
    *,
    credentials=None,
    max_pages: int | None = None,
    max_users: int | None = None,
    rate_limit_retries: int = 3,
) -> list[tuple[str, str]]:
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, timeout=5.0) as client:
        adapter = ManagementExtractAdapter(
            http_client=client,
            max_pages=max_pages,
            max_users=max_users,
            poll_interval_seconds=0,
            poll_timeout_seconds=5,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=0,
        )
        return [row async for row in adapter.iter_users(credentials or _CREDENTIALS)]


@pytest.mark.asyncio
async def test_iter_users_yields_vendor_id_and_email() -> None:
    handler = _export_handler([{"user_id": "auth0|aaa", "email": _EMAIL_A}])
    rows = await _collect(handler)
    assert rows == [("auth0|aaa", _EMAIL_A)]


@pytest.mark.asyncio
async def test_iter_users_accepts_prod_style_export_host() -> None:
    """Real tenant export hosts carry ``-export-users`` without an ``auth0-`` prefix."""
    location = f"https://{_EXPORT_HOST_PROD}/exports/users.json.gz"
    handler = _export_handler([{"user_id": "auth0|aaa", "email": _EMAIL_A}], location=location)
    rows = await _collect(handler)
    assert rows == [("auth0|aaa", _EMAIL_A)]
    assert _EXPORT_HOST_PROD in handler.state["hosts"]


@pytest.mark.asyncio
async def test_iter_users_accepts_object_credentials() -> None:
    handler = _export_handler([{"user_id": "auth0|obj", "email": _EMAIL_A}])
    rows = await _collect(
        handler,
        credentials=_ObjectCredentials(
            domain=_DOMAIN, client_id=_CLIENT_ID, client_secret=_CLIENT_SECRET
        ),
    )
    assert rows == [("auth0|obj", _EMAIL_A)]


@pytest.mark.asyncio
async def test_iter_users_exports_more_than_1000_users() -> None:
    users = [
        {"user_id": f"auth0|{index:04d}", "email": f"user{index:04d}@example.com"}
        for index in range(1205)
    ]
    handler = _export_handler(users, polls_before_done=2)
    rows = await _collect(handler)
    assert len(rows) == 1205
    assert rows[0] == ("auth0|0000", "user0000@example.com")
    assert rows[-1] == ("auth0|1204", "user1204@example.com")
    assert "/api/v2/users" not in handler.state["paths"]
    assert all("page" not in query for query in handler.state["queries"])


@pytest.mark.asyncio
async def test_iter_users_never_requests_offset_page_10() -> None:
    users = [
        {"user_id": f"auth0|{index}", "email": f"u{index}@example.com"}
        for index in range(1000)
    ]
    handler = _export_handler(users)
    rows = await _collect(handler)
    assert len(rows) == 1000
    assert "/api/v2/users" not in handler.state["paths"]
    for query in handler.state["queries"]:
        assert "page" not in query
        assert query.get("page") != ["10"]


@pytest.mark.asyncio
async def test_iter_users_stops_on_empty_ndjson_lines() -> None:
    handler = _export_handler(
        [
            {"user_id": "auth0|a", "email": _EMAIL_A},
            {"user_id": "auth0|b", "email": _EMAIL_B},
        ]
    )
    rows = await _collect(handler)
    assert rows == [("auth0|a", _EMAIL_A), ("auth0|b", _EMAIL_B)]


@pytest.mark.asyncio
async def test_iter_users_skips_users_without_email() -> None:
    handler = _export_handler(
        [
            {"user_id": "auth0|no-email"},
            {"user_id": "auth0|blank", "email": "   "},
            {"user_id": "auth0|ok", "email": _EMAIL_A},
            {"email": _EMAIL_B},
        ]
    )
    rows = await _collect(handler)
    assert rows == [("auth0|ok", _EMAIL_A)]


@pytest.mark.asyncio
async def test_iter_users_normalizes_https_domain() -> None:
    handler = _export_handler([])
    rows = await _collect(
        handler,
        credentials={
            "domain": f"https://{_DOMAIN}/",
            "client_id": _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
        },
    )
    assert rows == []
    assert handler.state["paths"][0] == "/oauth/token"


@pytest.mark.asyncio
async def test_iter_users_max_pages_does_not_silently_truncate() -> None:
    handler = _export_handler(
        [
            {"user_id": "auth0|1", "email": _EMAIL_A},
            {"user_id": "auth0|2", "email": _EMAIL_B},
            {"user_id": "auth0|3", "email": _EMAIL_C},
        ]
    )
    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler, max_pages=2)
    assert exc_info.value.code == "export_incomplete"


@pytest.mark.asyncio
async def test_iter_users_env_max_pages_does_not_silently_truncate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH0_USERS_MAX_PAGES", "1")
    handler = _export_handler(
        [
            {"user_id": "auth0|1", "email": _EMAIL_A},
            {"user_id": "auth0|2", "email": _EMAIL_B},
        ]
    )
    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler)
    assert exc_info.value.code == "export_incomplete"


@pytest.mark.asyncio
async def test_iter_users_max_users_equals_export_size_is_complete() -> None:
    handler = _export_handler(
        [
            {"user_id": "auth0|1", "email": _EMAIL_A},
            {"user_id": "auth0|2", "email": _EMAIL_B},
        ]
    )
    rows = await _collect(handler, max_users=2)
    assert rows == [("auth0|1", _EMAIL_A), ("auth0|2", _EMAIL_B)]


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["", "   ", "not-a-host", "localhost", "bad host"])
async def test_iter_users_invalid_domain(domain: str) -> None:
    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(
            lambda _request: httpx.Response(500),
            credentials={
                "domain": domain,
                "client_id": _CLIENT_ID,
                "client_secret": _CLIENT_SECRET,
            },
        )
    assert exc_info.value.code == "invalid_config"


@pytest.mark.asyncio
async def test_iter_users_token_unauthorized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/token"
        return httpx.Response(401, json={"error": "access_denied"})

    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler)
    assert exc_info.value.code == "unauthorized"
    assert exc_info.value.status_code == 401
    assert exc_info.value.step == "oauth_token"


@pytest.mark.asyncio
async def test_iter_users_permission_denied() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token_response()
        return httpx.Response(403, json={"error": "insufficient_scope"})

    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler)
    assert exc_info.value.code == "permission_denied"
    assert exc_info.value.step == "users_export"


@pytest.mark.asyncio
async def test_iter_users_retries_429_then_succeeds() -> None:
    hits = {"export": 0}

    def on_request(request: httpx.Request, _state: dict) -> httpx.Response | None:
        if request.url.path == "/api/v2/jobs/users-exports":
            hits["export"] += 1
            if hits["export"] == 1:
                return httpx.Response(
                    429,
                    json={"error": "too_many_requests"},
                    headers={"Retry-After": "0"},
                )
        return None

    handler = _export_handler(
        [{"user_id": "auth0|ok", "email": _EMAIL_A}],
        extra={"on_request": on_request},
    )
    rows = await _collect(handler)
    assert rows == [("auth0|ok", _EMAIL_A)]
    assert hits["export"] == 2


@pytest.mark.asyncio
async def test_iter_users_rate_limited_after_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token_response()
        return httpx.Response(429, json={"error": "too_many_requests"})

    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler, rate_limit_retries=2)
    assert exc_info.value.code == "rate_limited"


@pytest.mark.asyncio
async def test_iter_users_timeout_on_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler)
    assert exc_info.value.code == "timeout"


@pytest.mark.asyncio
async def test_iter_users_export_job_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return _token_response()
        if request.url.path == "/api/v2/jobs/users-exports":
            return httpx.Response(
                200,
                json={"id": _JOB_ID, "type": "users_export", "status": "pending"},
            )
        if request.url.path == f"/api/v2/jobs/{_JOB_ID}":
            return httpx.Response(
                200,
                json={"id": _JOB_ID, "type": "users_export", "status": "failed"},
            )
        return httpx.Response(404)

    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler)
    assert exc_info.value.code == "export_failed"


@pytest.mark.asyncio
async def test_iter_users_never_calls_logs_orgs_roles_or_users_list() -> None:
    handler = _export_handler([])
    await _collect(handler)
    paths = handler.state["paths"]
    assert paths[0] == "/oauth/token"
    assert "/api/v2/jobs/users-exports" in paths
    assert f"/api/v2/jobs/{_JOB_ID}" in paths
    assert "/api/v2/users" not in paths
    assert "/api/v2/logs" not in paths
    assert "/api/v2/organizations" not in paths
    assert "/api/v2/roles" not in paths


@pytest.mark.asyncio
async def test_iter_users_download_omits_bearer() -> None:
    handler = _export_handler([{"user_id": "auth0|a", "email": _EMAIL_A}])
    await _collect(handler)
    assert handler.state["export_auth"] == [None]


@pytest.mark.asyncio
async def test_iter_users_never_logs_email_or_client_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler = _export_handler(
        [
            {"user_id": "auth0|logged", "email": _EMAIL_A},
            {"user_id": "auth0|skip-me"},
        ]
    )
    with caplog.at_level(logging.DEBUG):
        await _collect(handler)

    blob = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("auth0.adapters.management")
    )
    assert _CLIENT_SECRET not in blob
    assert _EMAIL_A not in blob
    assert _TOKEN not in blob
    assert _EXPORT_URL not in blob
    assert "auth0|skip-me" not in blob
    assert "auth0|logged" not in blob


def test_required_scopes_documented() -> None:
    assert ManagementExtractAdapter.required_scopes == ("read:users",)
    assert DirectAdapter is ManagementExtractAdapter


@pytest.mark.asyncio
async def test_exception_message_is_allowlisted_code_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"denied for {_EMAIL_A} secret={_CLIENT_SECRET}")

    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler)
    assert str(exc_info.value) == "unauthorized"
    assert _EMAIL_A not in str(exc_info.value)
    assert _CLIENT_SECRET not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_iter_users_rejects_non_object_ndjson() -> None:
    body = gzip.compress(b'[{"user_id":"auth0|a","email":"a@example.com"}]\n')
    handler = _export_handler([], export_body=body)
    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler)
    assert exc_info.value.code == "bad_response"
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_iter_users_rejects_invalid_ndjson_line() -> None:
    body = gzip.compress(b'{"user_id":"auth0|a","email":"a@example.com"}\nnot-json\n')
    handler = _export_handler([], export_body=body)
    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler)
    assert exc_info.value.code == "bad_response"
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_iter_users_empty_file_when_job_claimed_users_fails() -> None:
    handler = _export_handler([], summary={"total": 12})
    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler)
    assert exc_info.value.code == "export_incomplete"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/",
        "http://metadata.google.internal/",
        "https://metadata.google.internal/",
        "https://evil-bucket.s3.us-east-2.amazonaws.com/users.json.gz",
    ],
)
async def test_iter_users_rejects_unexpected_export_location(location: str) -> None:
    handler = _export_handler([{"user_id": "auth0|a", "email": _EMAIL_A}], location=location)
    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler)
    assert exc_info.value.code == "bad_response"
    assert urlparse(location).hostname not in handler.state["hosts"]
    assert location not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_iter_users_download_timeout_does_not_chain_url() -> None:
    def on_request(request: httpx.Request, _state: dict) -> httpx.Response | None:
        if request.url.host == _EXPORT_HOST:
            raise httpx.ReadTimeout("slow")
        return None

    handler = _export_handler(
        [{"user_id": "auth0|a", "email": _EMAIL_A}],
        extra={"on_request": on_request},
    )
    with pytest.raises(ManagementApiError) as exc_info:
        await _collect(handler)
    assert exc_info.value.code == "timeout"
    assert exc_info.value.__cause__ is None
    assert _EXPORT_URL not in str(exc_info.value)
    assert _EXPORT_HOST not in str(exc_info.value)
