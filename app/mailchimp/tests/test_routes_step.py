"""Route behavior — step-scoped claim and matching freshness gate."""

import json
from unittest.mock import AsyncMock, patch

from habeas_privacy_core.connections.freshness import GateResult
from fastapi.testclient import TestClient


class _Acquire:
    def __init__(self, conn=None):
        self._conn = conn or AsyncMock()

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return None


class _FakePool:
    def __init__(self, conn=None):
        self._conn = conn or AsyncMock()

    def acquire(self):
        return _Acquire(self._conn)


def _gate_ok() -> GateResult:
    return GateResult(allowed=True, code="ok", display_status="connected")


def test_matching_submit_claims_matching_step():
    from mailchimp import main

    claim_row = {
        "id": 42,
        "request_id": "00000000-0000-0000-0000-000000000001",
        "step": "matching",
    }

    original_db_url = main.settings.database_url
    main.settings.database_url = "postgresql://test"
    try:
        with patch.object(main, "claim_next", new_callable=AsyncMock) as claim_next:
            with patch.object(main, "get_pool", return_value=_FakePool()):
                with patch.object(
                    main,
                    "evaluate_vertical_matching_gate",
                    new_callable=AsyncMock,
                    return_value=_gate_ok(),
                ) as evaluate_gate:
                    with patch.object(
                        main, "_complete_stub", new_callable=AsyncMock
                    ) as complete_stub:
                        claim_next.return_value = claim_row
                        complete_stub.return_value = {
                            "attempt_id": 42,
                            "step": "matching",
                            "status": "success",
                        }

                        client = TestClient(main.app)
                        response = client.post("/matching/submit")

                        assert response.status_code == 200
                        body = response.json()
                        assert body["claimed"] is True
                        assert body["step"] == "matching"
                        assert body["status"] == "success"

                        claim_next.assert_awaited_once()
                        evaluate_gate.assert_awaited_once()
                        assert evaluate_gate.await_args.kwargs["system"] == "mailchimp"
                        complete_stub.assert_awaited_once()
                        _conn, table, step = claim_next.await_args.args
                        assert table == main.ATTEMPTS_TABLE
                        assert step == "matching"
                        assert claim_next.await_args.kwargs["worker_id"] == main.settings.worker_id
    finally:
        main.settings.database_url = original_db_url


def test_matching_submit_idle_when_no_rows():
    from mailchimp import main

    original_db_url = main.settings.database_url
    main.settings.database_url = "postgresql://test"
    try:
        with patch.object(main, "claim_next", new_callable=AsyncMock) as claim_next:
            with patch.object(main, "get_pool", return_value=_FakePool()):
                claim_next.return_value = None

                client = TestClient(main.app)
                response = client.post("/matching/submit")

        assert response.status_code == 200
        assert response.json() == {"claimed": False}
    finally:
        main.settings.database_url = original_db_url


def test_matching_submit_blocks_stale_upload():
    """AE3: Upload past cadence → gate_blocked; no successful match."""
    from mailchimp import main

    claim_row = {
        "id": 42,
        "request_id": "00000000-0000-0000-0000-000000000001",
        "step": "matching",
    }
    blocked = GateResult(
        allowed=False, code="upload_stale", display_status="needs_refresh"
    )

    original_db_url = main.settings.database_url
    main.settings.database_url = "postgresql://test"
    try:
        with patch.object(main, "claim_next", new_callable=AsyncMock) as claim_next:
            with patch.object(main, "get_pool", return_value=_FakePool()):
                with patch.object(
                    main,
                    "evaluate_vertical_matching_gate",
                    new_callable=AsyncMock,
                    return_value=blocked,
                ):
                    with patch.object(
                        main, "_complete_gate_blocked", new_callable=AsyncMock
                    ) as complete_gate:
                        with patch.object(
                            main, "_complete_stub", new_callable=AsyncMock
                        ) as complete_stub:
                            claim_next.return_value = claim_row
                            complete_gate.return_value = {
                                "attempt_id": 42,
                                "step": "matching",
                                "status": "gate_blocked",
                            }

                            client = TestClient(main.app)
                            response = client.post("/matching/submit")

        assert response.status_code == 200
        body = response.json()
        assert body["claimed"] is True
        assert body["status"] == "gate_blocked"
        complete_gate.assert_awaited_once_with(42, blocked)
        complete_stub.assert_not_awaited()
    finally:
        main.settings.database_url = original_db_url


def test_matching_submit_blocks_rotation_overdue():
    """AE4: Live credential rotation overdue → gate_blocked."""
    from mailchimp import main

    claim_row = {
        "id": 44,
        "request_id": "00000000-0000-0000-0000-000000000004",
        "step": "matching",
    }
    blocked = GateResult(
        allowed=False, code="rotation_overdue", display_status="action_required"
    )

    original_db_url = main.settings.database_url
    main.settings.database_url = "postgresql://test"
    try:
        with patch.object(main, "claim_next", new_callable=AsyncMock) as claim_next:
            with patch.object(main, "get_pool", return_value=_FakePool()):
                with patch.object(
                    main,
                    "evaluate_vertical_matching_gate",
                    new_callable=AsyncMock,
                    return_value=blocked,
                ):
                    with patch.object(
                        main, "_complete_gate_blocked", new_callable=AsyncMock
                    ) as complete_gate:
                        with patch.object(
                            main, "_complete_stub", new_callable=AsyncMock
                        ) as complete_stub:
                            claim_next.return_value = claim_row
                            complete_gate.return_value = {
                                "attempt_id": 44,
                                "step": "matching",
                                "status": "gate_blocked",
                            }

                            client = TestClient(main.app)
                            response = client.post("/matching/submit")

        assert response.status_code == 200
        assert response.json()["status"] == "gate_blocked"
        complete_gate.assert_awaited_once()
        complete_stub.assert_not_awaited()
    finally:
        main.settings.database_url = original_db_url


def test_matching_submit_blocks_wizard_incomplete():
    from mailchimp import main

    claim_row = {
        "id": 45,
        "request_id": "00000000-0000-0000-0000-000000000005",
        "step": "matching",
    }
    blocked = GateResult(
        allowed=False, code="wizard_incomplete", display_status="action_required"
    )

    original_db_url = main.settings.database_url
    main.settings.database_url = "postgresql://test"
    try:
        with patch.object(main, "claim_next", new_callable=AsyncMock) as claim_next:
            with patch.object(main, "get_pool", return_value=_FakePool()):
                with patch.object(
                    main,
                    "evaluate_vertical_matching_gate",
                    new_callable=AsyncMock,
                    return_value=blocked,
                ):
                    with patch.object(
                        main, "_complete_gate_blocked", new_callable=AsyncMock
                    ) as complete_gate:
                        with patch.object(
                            main, "_complete_stub", new_callable=AsyncMock
                        ) as complete_stub:
                            claim_next.return_value = claim_row
                            complete_gate.return_value = {
                                "attempt_id": 45,
                                "step": "matching",
                                "status": "gate_blocked",
                            }

                            client = TestClient(main.app)
                            response = client.post("/matching/submit")

        assert response.status_code == 200
        assert response.json()["status"] == "gate_blocked"
        complete_stub.assert_not_awaited()
        complete_gate.assert_awaited_once()
    finally:
        main.settings.database_url = original_db_url


async def test_complete_gate_blocked_writes_allowlisted_audit():
    from mailchimp import main

    conn = AsyncMock()
    gate = GateResult(
        allowed=False, code="upload_stale", display_status="needs_refresh"
    )

    with patch.object(main, "get_pool", return_value=_FakePool(conn)):
        result = await main._complete_gate_blocked(99, gate)

    assert result == {
        "attempt_id": 99,
        "step": "matching",
        "status": "gate_blocked",
    }
    conn.execute.assert_awaited_once()
    args = conn.execute.await_args.args
    assert args[1] == 99
    assert args[2] == "submit_error"
    audit = json.loads(args[3])
    assert audit["event"] == "gate_blocked"
    assert audit["system"] == "mailchimp"
    assert audit["gate_code"] == "upload_stale"
    assert audit["display_status"] == "needs_refresh"
    assert audit["error_code"] == "gate_blocked"


def test_suppression_submit_claims_suppression_step():
    from mailchimp import main

    claim_row = {
        "id": 43,
        "request_id": "00000000-0000-0000-0000-000000000002",
        "step": "suppression",
    }

    original_db_url = main.settings.database_url
    main.settings.database_url = "postgresql://test"
    try:
        with patch.object(main, "claim_next", new_callable=AsyncMock) as claim_next:
            with patch.object(main, "get_pool", return_value=_FakePool()):
                with patch.object(main, "_complete_stub", new_callable=AsyncMock) as complete_stub:
                    with patch.object(
                        main, "evaluate_vertical_matching_gate", new_callable=AsyncMock
                    ) as evaluate_gate:
                        claim_next.return_value = claim_row
                        complete_stub.return_value = {
                            "attempt_id": 43,
                            "step": "suppression",
                            "status": "success",
                        }

                        client = TestClient(main.app)
                        response = client.post("/suppression/submit")

        assert response.status_code == 200
        body = response.json()
        assert body["claimed"] is True
        assert body["step"] == "suppression"
        _conn, table, step = claim_next.await_args.args
        assert table == "mailchimp_attempts"
        assert step == "suppression"
        evaluate_gate.assert_not_awaited()
    finally:
        main.settings.database_url = original_db_url


def test_hash_refresh_process_claims_mailchimp_system():
    from mailchimp import main

    claim_row = {"id": 3, "system": "mailchimp", "status": "claimed"}

    original_db_url = main.settings.database_url
    main.settings.database_url = "postgresql://test"
    try:
        with (
            patch.object(main, "get_pool", return_value=_FakePool()),
            patch.object(
                main,
                "claim_vertical_hash_refresh",
                new_callable=AsyncMock,
                return_value=claim_row,
            ) as mock_claim,
            patch.object(main, "mark_vertical_hash_refresh_in_flight", new_callable=AsyncMock),
            patch.object(main, "record_vertical_hash_refresh_run", new_callable=AsyncMock),
        ):
            # execute on conn for success UPDATE
            client = TestClient(main.app)
            response = client.post("/hash-refresh/process")

        assert response.status_code == 200
        body = response.json()
        assert body["processed"] is True
        assert body["attempt_id"] == 3
        mock_claim.assert_awaited_once()
        assert mock_claim.await_args.kwargs["system"] == "mailchimp"
    finally:
        main.settings.database_url = original_db_url
