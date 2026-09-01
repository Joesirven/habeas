"""Matching gate loader — per-system vs vertical AND (R9 / KTD10)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from habeas_privacy_core.connections.freshness import DisplayStatus, GateCode
from habeas_privacy_core.connections.matching_gate import (
    evaluate_matching_drain_readiness,
    evaluate_system_matching_gate,
    evaluate_vertical_matching_gate,
    gate_block_audit,
    vertical_id_from_attempt_row,
)

_NOW = datetime(2026, 8, 12, 16, 0, tzinfo=UTC)


def _meta(
    *,
    vertical_id: str,
    mode: str,
    wizard: bool = True,
    upload_at: str | None = "2026-08-11T00:00:00+00:00",
    rotated_at: str | None = "2026-08-01T00:00:00+00:00",
) -> dict[str, str]:
    metadata: dict[str, str] = {
        "vertical_id": vertical_id,
        "active_mode": mode,
        "cadence_days": "30",
    }
    if wizard:
        metadata["wizard_completed_at"] = "2026-07-01T00:00:00+00:00"
    if mode == "upload" and upload_at:
        metadata["last_successful_upload_at"] = upload_at
    if mode == "live" and rotated_at:
        metadata["credentials_rotated_at"] = rotated_at
    return metadata


def _row(system: str, metadata: dict, *, status: str = "connected") -> dict:
    return {
        "system": system,
        "status": status,
        "last_test_ok": True,
        "metadata": metadata,
    }


def _conn_for(rows: dict[str, dict | None]) -> AsyncMock:
    conn = AsyncMock()

    async def fetchrow(sql: str, *args: object):
        system = args[0]
        vertical_id = args[1] if len(args) > 1 else None
        row = rows.get(str(system))
        if row is None:
            return None
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        if vertical_id is not None and meta.get("vertical_id") != vertical_id:
            return None
        return row

    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    return conn


@pytest.mark.asyncio
async def test_system_gate_missing_row_is_wizard_incomplete() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    gate = await evaluate_system_matching_gate(conn, system="lever", now=_NOW)
    assert gate.allowed is False
    assert gate.code == GateCode.WIZARD_INCOMPLETE


@pytest.mark.asyncio
async def test_system_gate_stale_upload() -> None:
    conn = _conn_for(
        {
            "paylocity": _row(
                "paylocity",
                _meta(
                    vertical_id="people_hr",
                    mode="upload",
                    upload_at="2026-06-01T00:00:00+00:00",
                ),
            )
        }
    )
    gate = await evaluate_system_matching_gate(
        conn, system="paylocity", vertical_id="people_hr", now=_NOW
    )
    assert gate.allowed is False
    assert gate.code == GateCode.UPLOAD_STALE
    sql = conn.fetchrow.await_args.args[0]
    assert "vertical_id" in sql
    assert conn.fetchrow.await_args.args[2] == "people_hr"


@pytest.mark.asyncio
async def test_system_gate_does_not_select_other_vertical_row() -> None:
    conn = _conn_for(
        {
            "axios_headquarters": _row(
                "axios_headquarters",
                _meta(vertical_id="other_vertical", mode="upload"),
            )
        }
    )
    gate = await evaluate_system_matching_gate(
        conn, system="axios_headquarters", vertical_id="communications", now=_NOW
    )
    assert gate.allowed is False
    assert gate.code == GateCode.WIZARD_INCOMPLETE


@pytest.mark.asyncio
async def test_system_gate_parses_json_metadata_string() -> None:
    meta = _meta(vertical_id="communications", mode="upload")
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value=_row("axios_headquarters", json.dumps(meta))
    )
    gate = await evaluate_system_matching_gate(
        conn, system="axios_headquarters", vertical_id="communications", now=_NOW
    )
    assert gate.allowed is True
    assert gate.code == GateCode.OK


@pytest.mark.asyncio
async def test_vertical_gate_allows_communications_when_axios_headquarters_passes() -> None:
    conn = _conn_for(
        {
            "axios_headquarters": _row(
                "axios_headquarters",
                _meta(vertical_id="communications", mode="upload"),
            )
        }
    )
    gate = await evaluate_vertical_matching_gate(
        conn, system="axios_headquarters", vertical_id="communications", now=_NOW
    )
    assert gate.allowed is True
    assert gate.code == GateCode.OK


@pytest.mark.asyncio
async def test_vertical_gate_blocks_communications_when_axios_headquarters_stale() -> None:
    conn = _conn_for(
        {
            "axios_headquarters": _row(
                "axios_headquarters",
                _meta(
                    vertical_id="communications",
                    mode="upload",
                    upload_at="2026-06-01T00:00:00+00:00",
                ),
            )
        }
    )
    gate = await evaluate_vertical_matching_gate(
        conn, system="axios_headquarters", vertical_id="communications", now=_NOW
    )
    assert gate.allowed is False
    assert gate.code == GateCode.UPLOAD_STALE
    assert gate.blocking_system == "axios_headquarters"


@pytest.mark.asyncio
async def test_vertical_gate_blocks_lever_when_paylocity_stale() -> None:
    """R9 / KTD10: People/HR matching is blocked when any sibling fails."""
    conn = _conn_for(
        {
            "lever": _row("lever", _meta(vertical_id="people_hr", mode="live")),
            "paylocity": _row(
                "paylocity",
                _meta(
                    vertical_id="people_hr",
                    mode="upload",
                    upload_at="2026-06-01T00:00:00+00:00",
                ),
            ),
            "hr_alumni": _row(
                "hr_alumni",
                _meta(vertical_id="people_hr", mode="upload"),
            ),
            "alumni_google_sheet": _row(
                "alumni_google_sheet",
                {
                    **_meta(vertical_id="people_hr", mode="live"),
                    "last_successful_refresh_at": "2026-08-11T00:00:00+00:00",
                },
            ),
        }
    )
    own = await evaluate_system_matching_gate(
        conn, system="lever", vertical_id="people_hr", now=_NOW
    )
    assert own.allowed is True

    vertical = await evaluate_vertical_matching_gate(
        conn, system="lever", vertical_id="people_hr", now=_NOW
    )
    assert vertical.allowed is False
    assert vertical.code == GateCode.UPLOAD_STALE
    assert vertical.blocking_system == "paylocity"
    assert vertical.display_status == DisplayStatus.NEEDS_REFRESH


@pytest.mark.asyncio
async def test_vertical_gate_blocks_when_sibling_missing() -> None:
    conn = _conn_for(
        {
            "lever": _row("lever", _meta(vertical_id="people_hr", mode="live")),
            "paylocity": _row(
                "paylocity", _meta(vertical_id="people_hr", mode="upload")
            ),
            # hr_alumni absent → wizard_incomplete
        }
    )
    gate = await evaluate_vertical_matching_gate(
        conn, system="lever", vertical_id="people_hr", now=_NOW
    )
    assert gate.allowed is False
    assert gate.code == GateCode.WIZARD_INCOMPLETE
    assert gate.blocking_system == "hr_alumni"


@pytest.mark.asyncio
async def test_vertical_gate_allows_when_all_people_hr_systems_pass() -> None:
    conn = _conn_for(
        {
            "lever": _row("lever", _meta(vertical_id="people_hr", mode="live")),
            "paylocity": _row(
                "paylocity", _meta(vertical_id="people_hr", mode="upload")
            ),
            "hr_alumni": _row(
                "hr_alumni", _meta(vertical_id="people_hr", mode="upload")
            ),
            "alumni_google_sheet": _row(
                "alumni_google_sheet",
                {
                    **_meta(vertical_id="people_hr", mode="live"),
                    "last_successful_refresh_at": "2026-08-11T00:00:00+00:00",
                },
            ),
        }
    )
    gate = await evaluate_vertical_matching_gate(
        conn, system="lever", now=_NOW
    )
    assert gate.allowed is True
    assert gate.code == GateCode.OK


@pytest.mark.asyncio
async def test_vertical_gate_skips_data_cassandra() -> None:
    conn = _conn_for(
        {
            "cassandra": _row(
                "cassandra",
                {"vertical_id": "data"},
                status="connected",
            )
        }
    )
    gate = await evaluate_vertical_matching_gate(
        conn, system="cassandra", vertical_id="data", now=_NOW
    )
    assert gate.allowed is True
    assert gate.code == GateCode.VIEW_ONLY


def test_gate_block_audit_allowlisted_and_blocking_system() -> None:
    from habeas_privacy_core.connections.freshness import GateResult

    payload = gate_block_audit(
        system="lever",
        gate=GateResult(
            allowed=False,
            code=GateCode.UPLOAD_STALE,
            display_status=DisplayStatus.NEEDS_REFRESH,
            blocking_system="paylocity",
        ),
    )
    assert payload == {
        "event": "gate_blocked",
        "system": "lever",
        "gate_code": "upload_stale",
        "display_status": "needs_refresh",
        "blocking_system": "paylocity",
    }
    assert "email" not in payload


def test_vertical_id_from_attempt_row() -> None:
    assert vertical_id_from_attempt_row({"vertical_id": "people_hr"}) == "people_hr"
    assert (
        vertical_id_from_attempt_row(
            {"audit_payload": {"vertical_id": "tech"}}
        )
        == "tech"
    )
    assert (
        vertical_id_from_attempt_row(
            {"audit_payload": json.dumps({"vertical_id": "communications"})}
        )
        == "communications"
    )
    assert vertical_id_from_attempt_row({}) is None
    assert vertical_id_from_attempt_row(None) is None


@pytest.mark.asyncio
async def test_evaluate_matching_drain_readiness_mart_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from habeas_privacy_core.connections.freshness import GateResult

    async def _ok_gate(*_a: object, **_k: object) -> GateResult:
        return GateResult(
            allowed=True, code=GateCode.OK, display_status=DisplayStatus.CONNECTED
        )

    monkeypatch.setattr(
        "habeas_privacy_core.connections.matching_gate.evaluate_system_matching_gate",
        _ok_gate,
    )
    monkeypatch.setattr(
        "habeas_privacy_core.connections.matching_gate.email_hash_mart_exists",
        lambda *_a, **_k: False,
    )
    out = await evaluate_matching_drain_readiness(
        AsyncMock(), system="hr_alumni", mart_table="hr_alumni_email_hash__build"
    )
    assert out.ready is False
    assert out.reason == "mart_missing"


@pytest.mark.asyncio
async def test_evaluate_matching_drain_readiness_gate_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from habeas_privacy_core.connections.freshness import GateResult

    async def _blocked(*_a: object, **_k: object) -> GateResult:
        return GateResult(
            allowed=False,
            code=GateCode.SHEETS_REFRESH_STALE,
            display_status=DisplayStatus.NEEDS_REFRESH,
        )

    monkeypatch.setattr(
        "habeas_privacy_core.connections.matching_gate.evaluate_system_matching_gate",
        _blocked,
    )
    monkeypatch.setattr(
        "habeas_privacy_core.connections.matching_gate.email_hash_mart_exists",
        lambda *_a, **_k: True,
    )
    out = await evaluate_matching_drain_readiness(AsyncMock(), system="hr_alumni")
    assert out.ready is False
    assert out.reason == "gate_blocked"
