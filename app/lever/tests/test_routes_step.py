"""Route behavior — step-scoped claim."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class _Acquire:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, *args):
        return None


class _FakePool:
    def acquire(self):
        return _Acquire()


def test_matching_submit_claims_matching_step():
    from lever import main

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
                with patch.object(main, "_complete_stub", new_callable=AsyncMock) as complete_stub:
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

        claim_next.assert_awaited_once()
        _conn, table, step = claim_next.await_args.args
        assert table == main.ATTEMPTS_TABLE
        assert table == "lever_attempts"
        assert step == "matching"
        assert claim_next.await_args.kwargs["worker_id"] == main.settings.worker_id
    finally:
        main.settings.database_url = original_db_url


def test_matching_submit_idle_when_no_rows():
    from lever import main

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


def test_suppression_submit_respects_suppress_lever_approval_gate():
    """Without suppress.lever approval, suppression submit must not complete."""
    from lever import main

    claim_row = {
        "id": 7,
        "request_id": "00000000-0000-0000-0000-000000000002",
        "step": "suppression",
    }
    active_rule = {
        "id": 1,
        "action_type": "suppress.lever",
        "requires_approval": True,
        "approver_role": "data_owner.hr",
    }

    original_db_url = main.settings.database_url
    main.settings.database_url = "postgresql://test"
    try:
        with patch.object(main, "claim_next", new_callable=AsyncMock) as claim_next:
            with patch.object(main, "get_pool", return_value=_FakePool()):
                with patch.object(main, "fetch_active_rule", new_callable=AsyncMock) as fetch_rule:
                    with patch.object(
                        main,
                        "_is_suppress_lever_approved",
                        new_callable=AsyncMock,
                    ) as is_approved:
                        with patch.object(
                            main,
                            "_release_claim",
                            new_callable=AsyncMock,
                        ) as release_claim:
                            with patch.object(
                                main,
                                "_complete_stub",
                                new_callable=AsyncMock,
                            ) as complete_stub:
                                claim_next.return_value = claim_row
                                fetch_rule.return_value = active_rule
                                is_approved.return_value = False

                                client = TestClient(main.app)
                                response = client.post("/suppression/submit")

        assert response.status_code == 200
        assert response.json() == {
            "claimed": False,
            "reason": "awaiting_suppress_lever_approval",
        }
        fetch_rule.assert_awaited_once()
        assert fetch_rule.await_args.args[1] == "suppress.lever"
        is_approved.assert_awaited_once()
        release_claim.assert_awaited_once()
        complete_stub.assert_not_awaited()
    finally:
        main.settings.database_url = original_db_url


def test_suppression_submit_fail_closed_when_rule_missing():
    """Missing suppress.lever rule must not allow suppression to complete."""
    from lever import main

    claim_row = {
        "id": 8,
        "request_id": "00000000-0000-0000-0000-000000000003",
        "step": "suppression",
    }

    original_db_url = main.settings.database_url
    main.settings.database_url = "postgresql://test"
    try:
        with patch.object(main, "claim_next", new_callable=AsyncMock) as claim_next:
            with patch.object(main, "get_pool", return_value=_FakePool()):
                with patch.object(main, "fetch_active_rule", new_callable=AsyncMock) as fetch_rule:
                    with patch.object(
                        main,
                        "_is_suppress_lever_approved",
                        new_callable=AsyncMock,
                    ) as is_approved:
                        with patch.object(
                            main,
                            "_release_claim",
                            new_callable=AsyncMock,
                        ) as release_claim:
                            with patch.object(
                                main,
                                "_complete_stub",
                                new_callable=AsyncMock,
                            ) as complete_stub:
                                claim_next.return_value = claim_row
                                fetch_rule.return_value = None
                                is_approved.return_value = False

                                client = TestClient(main.app)
                                response = client.post("/suppression/submit")

        assert response.status_code == 200
        assert response.json() == {
            "claimed": False,
            "reason": "awaiting_suppress_lever_approval",
        }
        is_approved.assert_awaited_once()
        release_claim.assert_awaited_once()
        complete_stub.assert_not_awaited()
    finally:
        main.settings.database_url = original_db_url
