"""Hermetic match-quality API — mocked connection, no live database."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from admin_api import drop_pipeline, match_quality, roles
from admin_api import main as admin_main
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER

_PII_KEYS = frozenset(
    {
        "consumer_id",
        "email",
        "emails",
        "phone",
        "email_hash",
        "phone_hash",
        "ndz_hash",
        "dwid",
        "dwids",
    }
)


def _response_keys(payload: dict[str, Any]) -> set[str]:
    keys = set(payload)
    for item in payload.get("by_parameter") or []:
        if isinstance(item, dict):
            keys.update(item)
    for item in payload.get("breaches") or []:
        if isinstance(item, dict):
            keys.update(item)
    return keys


def signed_headers(email: str, **extra: str) -> dict[str, str]:
    return {
        IAP_EMAIL_HEADER: f"accounts.google.com:{email}",
        "Authorization": f"Bearer {email}",
        **extra,
    }


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(drop_pipeline.settings, "database_url", "")
    monkeypatch.setattr(roles.settings, "database_url", "")
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "admin@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)


def _pool_with_conn(conn: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Acquire:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    pool = MagicMock()
    pool.acquire.return_value = _Acquire()
    monkeypatch.setattr(match_quality, "_require_database", lambda: None)
    monkeypatch.setattr(match_quality, "get_pool", lambda: pool)


def _row(
    parameter: str,
    *,
    requests: int,
    exact_single: int,
    any_hit: int,
    multi_hit: int = 0,
    zero_hit: int = 0,
    intake_source: str = "drop",
    requestor_state: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "parameter": parameter,
        "intake_source": intake_source,
        "requests": requests,
        "exact_single": exact_single,
        "any_hit": any_hit,
        "multi_hit": multi_hit,
        "zero_hit": zero_hit,
    }
    if requestor_state is not None:
        payload["requestor_state"] = requestor_state
    return payload


def test_aggregate_email_zero_hit_floor_from_prod_snapshot() -> None:
    rows = [
        _row("drop_hash_email", requests=607_239, exact_single=0, any_hit=0, zero_hit=607_239),
        _row(
            "drop_hash_ndz",
            requests=746_115,
            exact_single=407_913,
            any_hit=411_655,
            multi_hit=3_742,
            zero_hit=334_460,
        ),
        _row(
            "drop_hash_phone",
            requests=489_897,
            exact_single=236_402,
            any_hit=304_305,
            zero_hit=185_592,
        ),
    ]
    payload = match_quality.aggregate_match_quality(rows)
    by_parameter = {item.parameter: item for item in payload.by_parameter}
    email = by_parameter["drop_hash_email"]
    assert email.requests == 607_239
    assert email.exact_single == 0
    assert email.any_hit == 0
    assert email.exact_rate == 0.0
    assert email.any_hit_rate == 0.0
    ndz = by_parameter["drop_hash_ndz"]
    assert ndz.exact_rate == pytest.approx(407_913 / 746_115)
    assert ndz.any_hit_rate == pytest.approx(411_655 / 746_115)
    assert [b.code for b in payload.breaches] == [match_quality.BREACH_CODE_ZERO_HIT_FLOOR]
    assert payload.breaches[0].parameter == "drop_hash_email"
    assert payload.breaches[0].requests == 607_239
    keys = _response_keys(payload.model_dump())
    assert keys.isdisjoint(_PII_KEYS)


def test_aggregate_no_breach_below_floor() -> None:
    payload = match_quality.aggregate_match_quality(
        [_row("drop_hash_email", requests=999, exact_single=0, any_hit=0, zero_hit=999)]
    )
    assert payload.by_parameter[0].any_hit_rate == 0.0
    assert payload.breaches == []


def test_aggregate_sums_states_and_skips_non_drop() -> None:
    rows = [
        _row(
            "drop_hash_email",
            requests=800,
            exact_single=10,
            any_hit=20,
            requestor_state="CA",
        ),
        _row(
            "drop_hash_email",
            requests=200,
            exact_single=5,
            any_hit=10,
            requestor_state="NY",
        ),
        _row(
            "drop_hash_email",
            requests=50_000,
            exact_single=0,
            any_hit=0,
            intake_source="manual",
        ),
    ]
    payload = match_quality.aggregate_match_quality(rows)
    assert len(payload.by_parameter) == 1
    item = payload.by_parameter[0]
    assert item.requests == 1_000
    assert item.exact_single == 15
    assert item.any_hit == 30
    assert item.exact_rate == pytest.approx(0.015)
    assert item.any_hit_rate == pytest.approx(0.03)
    assert payload.breaches == []


def test_aggregate_empty_rows() -> None:
    payload = match_quality.aggregate_match_quality([])
    assert payload.by_parameter == []
    assert payload.breaches == []


@pytest.mark.asyncio
async def test_collect_uses_inline_select_when_i4_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(match_quality, "fetch_drop_match_totals", None)
    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[
            _row("drop_hash_email", requests=1_000, exact_single=0, any_hit=0, zero_hit=1_000)
        ]
    )
    payload = await match_quality.collect_match_quality(conn)
    conn.fetch.assert_awaited_once()
    sql, intake_source = conn.fetch.await_args.args
    assert "matching_parameter_stats" in sql
    assert intake_source == "drop"
    for forbidden in ("consumer_id", "email_hash", "phone_hash", "ndz_hash"):
        assert forbidden not in sql
    assert payload.breaches[0].code == match_quality.BREACH_CODE_ZERO_HIT_FLOOR


@pytest.mark.asyncio
async def test_collect_uses_i4_helper_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_i4(conn: Any) -> dict[str, Any]:
        _ = conn
        return {
            "intake_source": "drop",
            "by_parameter": [
                _row("drop_hash_phone", requests=10, exact_single=4, any_hit=6),
            ],
        }

    monkeypatch.setattr(match_quality, "fetch_drop_match_totals", fake_i4)
    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=AssertionError("inline SELECT must not run"))
    payload = await match_quality.collect_match_quality(conn)
    assert payload.by_parameter[0].parameter == "drop_hash_phone"
    assert payload.by_parameter[0].any_hit_rate == pytest.approx(0.6)
    conn.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_collect_reads_matching_parameter_stats_via_i4() -> None:
    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "parameter": "drop_hash_email",
                "requests": 1_000,
                "exact_single": 0,
                "any_hit": 0,
                "multi_hit": 0,
                "zero_hit": 1_000,
            }
        ]
    )
    payload = await match_quality.collect_match_quality(conn)
    conn.fetch.assert_awaited_once()
    sql, intake_source = conn.fetch.await_args.args
    assert "matching_parameter_stats" in sql
    assert "GROUP BY parameter" in sql
    assert intake_source == "drop"
    for forbidden in ("consumer_id", "email_hash", "phone_hash", "ndz_hash"):
        assert forbidden not in sql
    assert payload.breaches[0].code == "zero_hit_floor"


def test_match_quality_route_super_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[
            _row("drop_hash_email", requests=1_200, exact_single=0, any_hit=0, zero_hit=1_200),
            _row("drop_hash_ndz", requests=500, exact_single=100, any_hit=200, zero_hit=300),
        ]
    )
    _pool_with_conn(conn, monkeypatch)

    with TestClient(app) as client:
        denied = client.get(
            "/ops/drop/match-quality",
            headers=signed_headers("admin@example.com"),
        )
        assert denied.status_code == 403

        response = client.get(
            "/ops/drop/match-quality",
            headers=signed_headers("ops@example.com"),
        )

    assert response.status_code == 200
    body = response.json()
    assert {item["parameter"] for item in body["by_parameter"]} == {
        "drop_hash_email",
        "drop_hash_ndz",
    }
    email = next(item for item in body["by_parameter"] if item["parameter"] == "drop_hash_email")
    assert email["requests"] == 1_200
    assert email["exact_single"] == 0
    assert email["any_hit"] == 0
    assert email["any_hit_rate"] == 0.0
    assert email["exact_rate"] == 0.0
    assert body["breaches"] == [
        {
            "code": "zero_hit_floor",
            "parameter": "drop_hash_email",
            "requests": 1_200,
            "any_hit_rate": 0.0,
        }
    ]
    keys = _response_keys(body)
    assert keys.isdisjoint(_PII_KEYS)


def test_match_quality_requires_database() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/ops/drop/match-quality",
            headers=signed_headers("ops@example.com"),
        )
    assert response.status_code == 503
