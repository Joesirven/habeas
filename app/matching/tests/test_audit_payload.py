"""U11 — matching attempt audit JSONB allowlist + redaction."""

from __future__ import annotations

from datetime import datetime, timezone

from matching.audit_payload import build_matching_audit_payload


def test_audit_success_fields_no_pii():
    started = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 7, 17, 12, 0, 1, tzinfo=timezone.utc)
    payload = build_matching_audit_payload(
        started_at=started,
        completed_at=finished,
        attempt_number=1,
        list_type="Email",
        lookup_state="TX",
        bq_project="example-gcp-project",
        bq_dataset="drop_hash_index",
        bq_tables=["email_hash"],
        match_count=0,
        matched=False,
        matched_via="drop_hash_email",
        result_id=9,
    )
    assert payload["lookup_state"] == "TX"
    assert payload["match_count"] == 0
    assert payload["duration_ms"] == 1000
    assert "dwid" not in payload
    assert "hash" not in payload
    assert "email" not in payload


def test_audit_redacts_error_detail():
    payload = build_matching_audit_payload(
        error_code="bq_lookup_error",
        error_class="BigQueryLookupError",
        error_detail="boom dwid=999 email=jane@example.com hash=YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY=",
        retry_scheduled=True,
        attempt_number=3,
    )
    detail = payload["error_detail"]
    assert "999" not in detail
    assert "jane@example.com" not in detail
    assert "YWJj" not in detail
    assert "[redacted]" in detail
    assert payload["retry_scheduled"] is True


def test_matching_reaper_max_attempts_at_least_four():
    from habeas_privacy_core.queue.reap import ReapedTableConfig

    cfg = ReapedTableConfig(table="matching_attempts")
    assert cfg.max_attempts >= 4
