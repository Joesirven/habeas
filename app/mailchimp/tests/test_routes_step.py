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
