"""Matching result persistence — matching.review auto-create after success."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from habeas_privacy_core.workflow.approval import MATCHING_REVIEW_ACTION
from matching.results import complete_attempt_success, ensure_matching_review_pending

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.mark.asyncio
async def test_complete_attempt_success_creates_pending_matching_review_when_missing():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[99, None])
    requirement = MagicMock(rule_id=7, approver_role="compliance_lead")

    with patch(
        "matching.results.check_approval_required",
        new_callable=AsyncMock,
        return_value=requirement,
    ):
        result_id = await complete_attempt_success(
            conn,
            attempt_id=1,
            request_id=REQUEST_ID,
            matched=True,
            matched_via="drop_hash_email",
        )

    assert result_id == 99
    assert conn.execute.await_count == 2
    review_insert = conn.execute.await_args_list[1]
    assert review_insert.args[1] == UUID(REQUEST_ID)
    assert review_insert.args[2] == MATCHING_REVIEW_ACTION
    assert review_insert.args[3] == 7
    assert review_insert.args[4] == "compliance_lead"


@pytest.mark.asyncio
async def test_ensure_matching_review_pending_skips_when_already_exists():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)

    await ensure_matching_review_pending(conn, REQUEST_ID)

    conn.fetchval.assert_awaited_once()
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_matching_review_pending_skips_when_rule_not_required():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)

    with (
        patch(
            "matching.results.check_approval_required",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "matching.results.fetch_active_rule",
            new_callable=AsyncMock,
            return_value={"requires_approval": False},
        ),
    ):
        await ensure_matching_review_pending(conn, REQUEST_ID)

    conn.execute.assert_not_awaited()
