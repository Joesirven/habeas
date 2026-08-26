"""Unit and optional integration tests for connections core helpers."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from habeas_privacy_core.connections.catalog import (
    MATCHING_SYSTEM_COLOR_TOKENS,
    MATCHING_SYSTEM_LABELS,
    list_matching_review_systems,
)
from habeas_privacy_core.connections.models import (
    ALLOWED_TEST_DETAIL_CODES,
    sanitize_test_detail,
)
from habeas_privacy_core.connections.secrets import InMemorySecretWriter, get_secret_writer
from habeas_privacy_core.connections.token import (
    INVITE_TTL_HOURS,
    generate_invite_token,
    hash_token,
)
from habeas_privacy_core.db.connections import (
    consume_invite,
    create_invite,
    get_connection,
    get_invite_by_token_hash,
    insert_connection,
    list_connections,
    revoke_invite,
    secret_resource_name,
    set_test_result,
    update_connection_status,
)
from habeas_privacy_core.db.migrations import run_migrations

requires_database = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for connections integration tests",
)


def test_hash_token_is_sha256_hex():
    digest = hash_token("example-token")
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)
    assert digest == hash_token("example-token")


def test_generate_invite_token_unique():
    tokens = {generate_invite_token() for _ in range(20)}
    assert len(tokens) == 20


def test_generate_invite_token_roundtrip_hash():
    raw = generate_invite_token()
    assert raw
    assert hash_token(raw) != raw


def test_sanitize_test_detail_allowlists_codes():
    assert sanitize_test_detail("stub_ok") == "stub_ok"
    assert sanitize_test_detail(" STUB_OK ") == "stub_ok"
    assert sanitize_test_detail("ok") == "ok"
    assert sanitize_test_detail(None) is None
    assert sanitize_test_detail("") is None


def test_sanitize_test_detail_allowlists_live_success_codes():
    for code in (
        "mailchimp_ok",
        "paylocity_ok",
        "lever_ok",
        "auth0_ok",
        "google_sheets_ok",
        "upload_ok",
    ):
        assert code in ALLOWED_TEST_DETAIL_CODES
        assert sanitize_test_detail(code) == code
        assert sanitize_test_detail(code.upper()) == code


def test_sanitize_test_detail_allowlists_failure_codes():
    for code in (
        "auth_failed",
        "unreachable",
        "invalid_credentials",
        "invalid_config",
        "upload_missing_headers",
        "upload_needs_mapping",
        "upload_no_usable_rows",
        "upload_rows_rejected",
        "upload_invalid_format",
        "upload_invalid_delimiter",
        "gate_blocked",
        "unknown_system",
        "infra_only",
        "missing_credentials",
        "failed",
        "unknown_error",
    ):
        assert code in ALLOWED_TEST_DETAIL_CODES
        assert sanitize_test_detail(code) == code


def test_sanitize_test_detail_rejects_vendor_payloads():
    assert sanitize_test_detail("HTTP 401: invalid api_key=secret123") == "unknown_error"
    assert (
        sanitize_test_detail('{"title":"Invalid API Key","status":401,"detail":"Bad key"}')
        == "unknown_error"
    )
    assert sanitize_test_detail("mailchimp_ok but with extra vendor text") == "unknown_error"


def test_invite_ttl_constant():
    assert INVITE_TTL_HOURS == 72


def test_in_memory_secret_writer_put_and_get():
    writer = InMemorySecretWriter()
    writer.put_secret("dpra/connections/mailchimp/abc", '{"api_key":"x"}')
    assert writer.get_secret("dpra/connections/mailchimp/abc") == '{"api_key":"x"}'


def test_in_memory_secret_writer_overwrites():
    writer = InMemorySecretWriter()
    writer.put_secret("secret-id", "first")
    writer.put_secret("secret-id", "second")
    assert writer.get_secret("secret-id") == "second"


def test_get_secret_writer_defaults_to_in_memory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.delenv("SECRET_READER", raising=False)
    monkeypatch.delenv("SECRET_WRITER", raising=False)
    writer = get_secret_writer()
    assert isinstance(writer, InMemorySecretWriter)


def test_secret_resource_name_format():
    assert (
        secret_resource_name("mailchimp", "550e8400-e29b-41d4-a716-446655440000")
        == "dpra/connections/mailchimp/550e8400-e29b-41d4-a716-446655440000"
    )


def test_matching_review_systems_include_sheet_sources():
    rows = list_matching_review_systems()
    by_system = {row.system: row for row in rows}

    assert "bizdev_contacts" in by_system
    assert "hr_alumni" in by_system

    contact_us = by_system["bizdev_contacts"]
    alumni = by_system["hr_alumni"]
    assert contact_us.system_label == "Contact Us Google Sheet"
    assert alumni.system_label == "Alumni Google Sheet"
    assert contact_us.system_label == MATCHING_SYSTEM_LABELS["bizdev_contacts"]
    assert alumni.system_label == MATCHING_SYSTEM_LABELS["hr_alumni"]
    assert contact_us.vertical_id == "bizdev"
    assert alumni.vertical_id == "people_hr"

    cassandra = by_system["cassandra"]
    assert cassandra.vertical_id == "data"
    assert cassandra.system_label == "CA DROP"
    assert MATCHING_SYSTEM_LABELS["cassandra"] == "CA DROP"
    assert all(row.vertical_id != "test" for row in rows)

    for system in ("bizdev_contacts", "hr_alumni", "cassandra"):
        assert system in MATCHING_SYSTEM_COLOR_TOKENS
        assert by_system[system].color_token == MATCHING_SYSTEM_COLOR_TOKENS[system]
        assert by_system[system].color_token

    assert contact_us.color_token == "teal"
    assert alumni.color_token == "slate"
    assert alumni.color_token != "amber"

    assert all(row.color_token for row in rows)


def test_matching_review_systems_filter_bizdev_is_contact_us_only():
    rows = list_matching_review_systems(vertical_ids=frozenset({"bizdev"}))
    assert len(rows) == 1
    assert rows[0].system == "bizdev_contacts"
    assert rows[0].system_label == "Contact Us Google Sheet"
    assert rows[0].vertical_id == "bizdev"
    assert rows[0].vertical_label == "BizDev"


def test_matching_review_systems_filter_test_includes_cassandra_and_alumni():
    rows = list_matching_review_systems(vertical_ids=frozenset({"test"}))
    assert {row.system for row in rows} == {"cassandra", "hr_alumni"}
    assert {row.vertical_id for row in rows} == {"test"}
    assert all(row.vertical_label == "Test vertical" for row in rows)
    labels = {row.system: row.system_label for row in rows}
    assert labels == {"cassandra": "System A", "hr_alumni": "System B"}
    assert "CA DROP" not in labels.values()
    assert "Alumni Google Sheet" not in labels.values()


@pytest.fixture
async def pool():
    database_url = os.environ["DATABASE_URL"]
    run_migrations(database_url=database_url)
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    yield pool
    await pool.close()


async def _clear_connections(conn: asyncpg.Connection) -> None:
    await conn.execute("DELETE FROM connection_invites")
    await conn.execute("DELETE FROM integration_connections")


@requires_database
async def test_insert_and_get_connection(pool):
    async with pool.acquire() as conn:
        await _clear_connections(conn)

        created = await insert_connection(
            conn,
            system="mailchimp",
            display_name="Marketing list",
            created_by="super_admin@example.com",
            owner_email="owner@example.com",
        )
        loaded = await get_connection(conn, created.id)

        assert loaded is not None
        assert loaded.id == created.id
        assert loaded.system == "mailchimp"
        assert loaded.display_name == "Marketing list"
        assert loaded.status == "pending"
        assert loaded.owner_email == "owner@example.com"
        assert loaded.metadata == {}


@requires_database
async def test_list_connections_and_update_status(pool):
    async with pool.acquire() as conn:
        await _clear_connections(conn)

        first = await insert_connection(
            conn,
            system="lever",
            display_name="ATS",
            created_by="admin@example.com",
        )
        second = await insert_connection(
            conn,
            system="auth0",
            display_name="Identity",
            created_by="admin@example.com",
        )

        rows = await list_connections(conn)
        assert [row.id for row in rows] == [second.id, first.id]

        updated = await update_connection_status(
            conn,
            first.id,
            "invited",
            owner_email="owner@example.com",
            secret_resource_name=secret_resource_name("lever", first.id),
        )
        assert updated is not None
        assert updated.status == "invited"
        assert updated.owner_email == "owner@example.com"
        assert updated.secret_resource_name == secret_resource_name("lever", first.id)


@requires_database
async def test_invite_lifecycle(pool):
    async with pool.acquire() as conn:
        await _clear_connections(conn)

        connection = await insert_connection(
            conn,
            system="google_sheets",
            display_name="Ops sheet",
            created_by="admin@example.com",
        )
        raw = generate_invite_token()
        token_hash = hash_token(raw)
        expires_at = datetime.now(UTC) + timedelta(hours=INVITE_TTL_HOURS)

        invite = await create_invite(
            conn,
            connection_id=connection.id,
            token_hash=token_hash,
            owner_email="owner@example.com",
            expires_at=expires_at,
            created_by="admin@example.com",
        )
        loaded = await get_invite_by_token_hash(conn, token_hash)

        assert loaded is not None
        assert loaded.id == invite.id
        assert loaded.connection_id == connection.id
        assert loaded.consumed_at is None
        assert loaded.revoked_at is None

        consumed = await consume_invite(conn, invite.id)
        assert consumed is not None
        assert consumed.consumed_at is not None
        assert await consume_invite(conn, invite.id) is None


@requires_database
async def test_revoke_invite(pool):
    async with pool.acquire() as conn:
        await _clear_connections(conn)

        connection = await insert_connection(
            conn,
            system="paylocity",
            display_name="Payroll",
            created_by="admin@example.com",
        )
        token_hash = hash_token(generate_invite_token())
        invite = await create_invite(
            conn,
            connection_id=connection.id,
            token_hash=token_hash,
            owner_email="owner@example.com",
            expires_at=datetime.now(UTC) + timedelta(hours=INVITE_TTL_HOURS),
            created_by="admin@example.com",
        )

        revoked = await revoke_invite(conn, invite.id)
        assert revoked is not None
        assert revoked.revoked_at is not None
        assert await revoke_invite(conn, invite.id) is None


@requires_database
async def test_set_test_result(pool):
    async with pool.acquire() as conn:
        await _clear_connections(conn)

        connection = await insert_connection(
            conn,
            system="mailchimp",
            display_name="Newsletter",
            created_by="admin@example.com",
        )
        tested_at = datetime.now(UTC)
        updated = await set_test_result(
            conn,
            connection.id,
            ok=True,
            detail="stub_ok",
            tested_at=tested_at,
        )

        assert updated is not None
        assert updated.last_test_ok is True
        assert updated.last_test_detail == "stub_ok"
        assert updated.last_tested_at == tested_at
