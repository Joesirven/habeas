"""Unit tests for DROP-compatible vertical hash helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from habeas_privacy_core.vertical_hash import (
    HashedVendorRecord,
    email_hash_from_raw,
    hash_std,
    phone_hash_from_raw,
    standardize_email,
    standardize_phone,
)

# CPPA DROP v1.2.0 golden vectors (from drop_normalize/tests/test_cppa_vectors_v120.py)
EMAIL_VECTOR = (
    "Anna.Smith@Domain.com",
    "anna.smith@domain.com",
    "KA18MT/ph6IHYjzT9zwETySDQyvSh87YuoSBpOQtkhE=",
)

EMAIL_VECTOR_2 = (
    "danielle.johnson12@example.com",
    "danielle.johnson12@example.com",
    "mKDnDvwF2inxrKcK1hJN2TRkxPfL6kzNNTtU12eH8Bw=",
)

PHONE_VECTOR = (
    "+1(415)555-9317",
    "4155559317",
    "vGM7y5n+hBXRSEAklhHDPCbysyNgYTmXdMcagGUOY8E=",
)


class TestHashStd:
    @pytest.mark.parametrize(
        ("raw", "expected_std", "expected_hash"),
        [EMAIL_VECTOR, EMAIL_VECTOR_2],
    )
    def test_email_cppa_vectors(
        self, raw: str, expected_std: str, expected_hash: str
    ) -> None:
        assert standardize_email(raw) == expected_std
        assert hash_std(expected_std) == expected_hash
        assert email_hash_from_raw(raw) == expected_hash

    def test_phone_cppa_vector(self) -> None:
        raw, expected_std, expected_hash = PHONE_VECTOR
        assert standardize_phone(raw) == expected_std
        assert hash_std(expected_std) == expected_hash
        assert phone_hash_from_raw(raw) == expected_hash


class TestEmptyInputs:
    @pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
    def test_empty_email_returns_none(self, value: str | None) -> None:
        assert standardize_email(value) is None
        assert email_hash_from_raw(value) is None

    @pytest.mark.parametrize("value", [None, "", "   ", "abc"])
    def test_empty_phone_returns_none(self, value: str | None) -> None:
        assert standardize_phone(value) is None
        assert phone_hash_from_raw(value) is None


class TestHashedVendorRecord:
    def test_accepts_hashed_fields_only(self) -> None:
        record = HashedVendorRecord(
            system="mailchimp",
            vendor_record_id="mc-123",
            email_hash="KA18MT/ph6IHYjzT9zwETySDQyvSh87YuoSBpOQtkhE=",
            extracted_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        )
        assert record.system == "mailchimp"
        assert record.vendor_record_id == "mc-123"
        assert record.email_hash is not None
        assert record.phone_hash is None
        assert record.ndz_hash is None

    def test_has_no_plaintext_email_field(self) -> None:
        assert "email" not in HashedVendorRecord.model_fields
        assert "phone" not in HashedVendorRecord.model_fields
        assert "name" not in HashedVendorRecord.model_fields
        assert "dob" not in HashedVendorRecord.model_fields
        assert "zip" not in HashedVendorRecord.model_fields

    def test_rejects_plaintext_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            HashedVendorRecord(
                system="mailchimp",
                vendor_record_id="mc-123",
                email="anna.smith@domain.com",
                extracted_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
            )
