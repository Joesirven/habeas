"""Unit tests for attempt-table browser allowlists and projection."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from habeas_privacy_core.fleet.attempt_browser import (
    FORBIDDEN_ATTEMPT_COLUMNS,
    attempt_table_meta,
    build_safe_select,
    project_columns,
    project_row,
    validate_attempt_table_name,
)
from habeas_privacy_core.fleet.models import AttemptRowFilters


_AVAILABLE = (
    "id",
    "status",
    "step",
    "attempt_number",
    "attempted_at",
    "completed_at",
    "worker_id",
    "error_code",
    "error_message",
    "request_id",
    "audit_payload",
    "email",
    "raw_request_payload",
)


class TestValidateAndProject:
    def test_validate_good_table(self) -> None:
        assert validate_attempt_table_name("matching_attempts") == "matching_attempts"
        assert (
            validate_attempt_table_name("drop_ingest_attempts") == "drop_ingest_attempts"
        )

    def test_reject_denied_and_invalid(self) -> None:
        with pytest.raises(ValueError, match="denied"):
            validate_attempt_table_name("core_queue_test_attempts")
        with pytest.raises(ValueError, match="invalid queue table"):
            validate_attempt_table_name("Matching_Attempts")
        with pytest.raises(ValueError, match="not an attempt table"):
            validate_attempt_table_name("requests")

    def test_project_columns_strips_forbidden(self) -> None:
        cols = project_columns(_AVAILABLE)
        assert "id" in cols
        assert "error_message" in cols
        assert "audit_payload" not in cols
        assert "email" not in cols
        assert "raw_request_payload" not in cols
        for forbidden in FORBIDDEN_ATTEMPT_COLUMNS:
            assert forbidden not in cols

    def test_project_row_redacts_error_message(self) -> None:
        rid = uuid4()
        out = project_row(
            {
                "id": 1,
                "status": "failed",
                "error_message": "boom email=user@example.com dwid=abc123",
                "email": "user@example.com",
                "audit_payload": {"secret": True},
                "request_id": rid,
                "attempted_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
            },
            columns=["id", "status", "error_message", "request_id", "attempted_at"],
        )
        assert out["id"] == 1
        assert "email" not in out
        assert "audit_payload" not in out
        assert "user@example.com" not in out["error_message"]
        assert out["request_id"] == str(rid)
        assert out["attempted_at"].startswith("2026-08-01")


class TestSafeSelect:
    def test_build_safe_select_filters(self) -> None:
        rid = uuid4()
        spec = build_safe_select(
            "matching_attempts",
            available_columns=_AVAILABLE,
            filters=AttemptRowFilters(
                status=["pending", "claimed"],
                step="match",
                request_id=rid,
                limit=25,
            ),
        )
        assert spec.table == "matching_attempts"
        assert "audit_payload" not in spec.columns
        assert ("status", "in", ("pending", "claimed")) in spec.predicates
        assert ("step", "eq", "match") in spec.predicates
        assert ("request_id", "eq", rid) in spec.predicates
        assert spec.limit == 25
        assert "attempted_at" in spec.order_by

    def test_reject_bad_status(self) -> None:
        with pytest.raises(ValueError, match="status not allowlisted"):
            build_safe_select(
                "matching_attempts",
                available_columns=_AVAILABLE,
                filters=AttemptRowFilters(status=["DROP TABLE"]),
            )

    def test_reject_missing_filter_column(self) -> None:
        with pytest.raises(ValueError, match="step column not present"):
            build_safe_select(
                "matching_attempts",
                available_columns=["id", "status"],
                filters=AttemptRowFilters(step="x"),
            )

    def test_attempt_table_meta(self) -> None:
        meta = attempt_table_meta(
            "mailchimp_attempts",
            available_columns=_AVAILABLE,
        )
        assert meta.worker_key == "mailchimp"
        assert "status" in meta.filterable_columns
        assert "id" in meta.sortable_columns
        assert "email" not in meta.filterable_columns
