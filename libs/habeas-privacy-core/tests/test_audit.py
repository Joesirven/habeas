import json
import os

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from habeas_privacy_core.audit import (
    AuditMiddleware,
    actor_from_iap_header,
    command_from_request,
    interface_from_request,
    redact_error_text,
    redact_payload,
    trace_id_from_request,
    write_audit,
)
from habeas_privacy_core.db.migrations import migrations_dir, run_migrations
from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool

pytestmark_integration = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for audit integration tests",
)


def test_admin_audit_log_migration_exists():
    migration = migrations_dir() / "20260528000002_core_create_admin_audit_log.sql"
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE admin_audit_log" in content
    assert "REVOKE UPDATE, DELETE ON admin_audit_log FROM app_user" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_redact_payload_scrubs_known_patterns():
    payload = {
        "email": "user@example.com",
        "note": "Contact user@hidden.com or 415-555-0100",
        "ssn": "123-45-6789",
        "otp_code": "123456",
        "nested": {"phone": "5551234567"},
    }
    redacted = redact_payload(payload)
    assert redacted["email"] == "[REDACTED]"
    assert redacted["otp_code"] == "[REDACTED]"
    assert redacted["nested"]["phone"] == "[REDACTED]"
    assert "[REDACTED]" in redacted["note"]
    assert "[REDACTED]" in redacted["ssn"]


def test_redact_payload_scrubs_dwids_and_consumer_id():
    payload = {
        "dwids": ["1001", "1002"],
        "consumer_id": 5551212,
        "dispositions": [
            {"vertical": "credit", "selected_dwids": ["2001", "2002"]},
        ],
    }
    redacted = redact_payload(payload)
    assert redacted["dwids"] == ["[REDACTED]", "[REDACTED]"]
    assert redacted["consumer_id"] == "[REDACTED]"
    assert redacted["dispositions"][0]["selected_dwids"] == ["[REDACTED]", "[REDACTED]"]
    assert redacted["dispositions"][0]["vertical"] == "credit"


def test_redact_error_text_strips_hashes_dwids_and_pii():
    raw_kv = "failed near dwid=12345 hash=YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
    cleaned_kv = redact_error_text(raw_kv)
    assert "12345" not in cleaned_kv
    assert "YWJj" not in cleaned_kv
    assert "dwid=[redacted]" in cleaned_kv
    assert "[redacted]" in cleaned_kv
    assert not cleaned_kv.endswith("=")

    raw_json = '{"dwid": 999888, "hash": "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="}'
    cleaned_json = redact_error_text(raw_json)
    assert "999888" not in cleaned_json
    assert "YWJj" not in cleaned_json
    assert '"dwid":[redacted]' in cleaned_json

    assert "5551212" not in redact_error_text("lookup failed consumer_id=5551212")
    assert "consumer_id=[redacted]" in redact_error_text("lookup failed consumer_id=5551212")

    cleaned_email = redact_error_text("email=jane@example.com rejected")
    assert "jane@example.com" not in cleaned_email
    assert "[redacted]" in cleaned_email


def test_actor_and_interface_helpers():
    class _Headers(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class _Request:
        def __init__(self, headers, method="POST", path="/approvals/1/approve"):
            self.headers = _Headers(headers)
            self.method = method
            self.url = type("URL", (), {"path": path})()

    request = _Request({"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@example.com"})
    assert actor_from_iap_header(request) == "ops@example.com"
    assert interface_from_request(request) == "admin-api"
    assert command_from_request(request) == "POST /approvals/1/approve"
    assert trace_id_from_request(
        _Request({"X-Cloud-Trace-Context": "abc123/1;o=1"})
    ) == "abc123"

    cli_request = _Request({"X-Client": "habeas-cli"})
    assert interface_from_request(cli_request) == "cli"


@pytest.fixture
async def audit_pool():
    database_url = os.environ["DATABASE_URL"]
    run_migrations(database_url=database_url)
    await create_pool(database_url)
    yield get_pool()
    await close_pool()


@pytest.mark.asyncio
@pytestmark_integration
async def test_write_audit_persists_scrubbed_arguments(audit_pool):
    audit_id = await write_audit(
        actor="ops@example.com",
        interface="admin-api",
        command="POST /approvals/1/approve",
        arguments={"email": "secret@example.com", "reason": "approved"},
        result_status=200,
        result_summary="http_200",
        trace_id="trace-1",
        duration_ms=12,
    )
    assert audit_id > 0

    async with audit_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM admin_audit_log WHERE id = $1", audit_id)

    assert row["actor"] == "ops@example.com"
    assert row["interface"] == "admin-api"
    assert row["command"] == "POST /approvals/1/approve"
    assert row["result_status"] == 200
    assert row["trace_id"] == "trace-1"
    assert row["duration_ms"] == 12
    arguments = json.loads(row["arguments"]) if isinstance(row["arguments"], str) else row["arguments"]
    assert arguments["email"] == "[REDACTED]"


@pytest.mark.asyncio
@pytestmark_integration
async def test_app_user_cannot_update_or_delete_admin_audit_log(audit_pool):
    audit_id = await write_audit(
        actor="ops@example.com",
        interface="admin-api",
        command="POST /test",
        result_status=200,
    )

    async with audit_pool.acquire() as conn:
        await conn.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
                    CREATE ROLE app_user LOGIN;
                END IF;
            END $$;
            """
        )
        await conn.execute("GRANT INSERT, SELECT ON admin_audit_log TO app_user")
        await conn.execute("REVOKE UPDATE, DELETE ON admin_audit_log FROM app_user")

    async with audit_pool.acquire() as conn:
        await conn.execute("SET ROLE app_user")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(
                "UPDATE admin_audit_log SET actor = 'tampered' WHERE id = $1",
                audit_id,
            )

    async with audit_pool.acquire() as conn:
        await conn.execute("SET ROLE app_user")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("DELETE FROM admin_audit_log WHERE id = $1", audit_id)


@pytest.mark.asyncio
@pytestmark_integration
async def test_audit_middleware_writes_one_row_per_mutation(audit_pool):
    observed: list[int] = []

    async def approve(request: Request) -> JSONResponse:
        approval_id = int(request.path_params["approval_id"])
        observed.append(approval_id)
        return JSONResponse({"approved": approval_id})

    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    audit_app = Starlette(
        routes=[
            Route("/approvals/{approval_id}/approve", approve, methods=["POST"]),
            Route("/healthz", healthz, methods=["GET"]),
        ]
    )
    audit_app.add_middleware(AuditMiddleware)

    transport = ASGITransport(app=audit_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/approvals/7/approve",
            json={"note": "ok", "email": "user@example.com"},
            headers={
                "X-Goog-Authenticated-User-Email": "accounts.google.com:ops@example.com",
                "X-Cloud-Trace-Context": "trace-abc/1;o=1",
            },
        )
        health_response = await client.get("/healthz")

    assert response.status_code == 200
    assert observed == [7]
    assert health_response.status_code == 200

    async with audit_pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM admin_audit_log
             WHERE command = 'POST /approvals/7/approve'
            """
        )
        health_count = await conn.fetchval(
            "SELECT COUNT(*) FROM admin_audit_log WHERE command = 'GET /healthz'"
        )

    assert count == 1
    assert health_count == 0
