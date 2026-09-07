"""Unit tests for DROP-compatible vertical hash helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from habeas_privacy_core.vertical_hash import (
    HashedVendorRecord,
    email_hash_from_raw,
    hash_std,
    ndz_hash_from_parts,
    phone_hash_from_raw,
    standardize_dob,
    standardize_email,
    standardize_name,
    standardize_phone,
    standardize_zip,
)
from habeas_privacy_core.vertical_hash.hashing import assert_opaque_hash

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

ZIP_VECTORS = [
    ("91790-3771", "91790", "2FPZucR4x7U8KlM+SFAX4LPGhwNz/PIZUCSUdDh0o/s="),
    ("M1B 1A1", "m1b1a", "n8L9q8mVeT6Xt9/EeUNiTukGDrkbPJ3DvOEx14uElxk="),
    (" 00712345", "71234", "aeNUYKh7Xw5sqpxSbSP9eOHsj6iXewbUyavv89DIuhQ="),
    (" 00300-9999", "300", "mDvWFLta/s5as7YCP3EUfNe2vCMU+dJ690IlQcZVg4k="),
]

DOB_VECTOR = (
    "July 4, 1776",
    "17760704",
    "skXYXxBER6HQTZ3rXSZH1wVGLQ054mS5rbR/bwvzy4I=",
)

NAME_VECTORS = [
    ("Juan Pablo", "juanpablo", "91hIbrbzNeqHs3o81O5yNrXUj7wDd2shvZ6THKi9qz8="),
    ("Martinez", "martinez", "2wRPGbwBNxhShjRczx8GfS2c4cjvs4NJskeWloUNtp8="),
]

NDZ_INPUT = ("Danielle", "Johnson", "July 4, 1985", "91790")
NDZ_FINAL_HASH = "PQOfn1RffEKmqMmNAzDKKaoZCwxWbQZkQzPWmQo9REA="
NDZ_FIELD_HASHES = {
    "first_name_std": "danielle",
    "last_name_std": "johnson",
    "dob_std": "19850704",
    "zip_std": "91790",
    "first_name_hash": "5dUD1FgiKcTJq+JQ5JZUdlyIXrSbtJ338YYbt5/HNG4=",
    "last_name_hash": "K+TjOqPiH2/3rRRPj9WCKKHM47UDQLSAX/DGNIDuxIg=",
    "dob_hash": "IWi7qxOAbBJe0fNciDj76Eg84gmj40rB7aNMK/VnFOI=",
    "zip_hash": "2FPZucR4x7U8KlM+SFAX4LPGhwNz/PIZUCSUdDh0o/s=",
}


class TestAssertOpaqueHash:
    @pytest.mark.parametrize(
        "plaintext",
        [
            "JohnSmith",
            "John|Doe|19900101|90210",
            "abc",
            "short",
            "anna.smith@domain.com",
            "+1(415)555-9317",
            "4155559317",
            "",
            "   ",
            "has space inside",
        ],
    )
    def test_rejects_non_digest_shape(self, plaintext: str) -> None:
        with pytest.raises(ValueError, match="email_hash must not contain plaintext") as exc_info:
            assert_opaque_hash(plaintext, label="email_hash")
        assert plaintext.strip() == "" or plaintext not in str(exc_info.value)

    def test_accepts_email_phone_ndz_digests(self) -> None:
        email_digest = email_hash_from_raw(EMAIL_VECTOR[0])
        phone_digest = phone_hash_from_raw(PHONE_VECTOR[0])
        ndz_digest = ndz_hash_from_parts(*NDZ_INPUT)
        assert email_digest is not None
        assert phone_digest is not None
        assert ndz_digest is not None
        assert assert_opaque_hash(email_digest, label="email_hash") == email_digest
        assert assert_opaque_hash(phone_digest, label="phone_hash") == phone_digest
        assert assert_opaque_hash(ndz_digest, label="ndz_hash") == ndz_digest
        assert assert_opaque_hash(f"  {email_digest}  ", label="email_hash") == email_digest


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

    @pytest.mark.parametrize("value", [None, "", "   ", "---", "!!!"])
    def test_empty_name_returns_none(self, value: str | None) -> None:
        assert standardize_name(value) is None

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_dob_returns_none(self, value: str | None) -> None:
        assert standardize_dob(value) is None

    @pytest.mark.parametrize("value", [None, "", "   ", "---"])
    def test_empty_zip_returns_none(self, value: str | None) -> None:
        assert standardize_zip(value) is None


class TestZipDobNameVectors:
    @pytest.mark.parametrize(
        ("raw", "expected_std", "expected_hash"),
        ZIP_VECTORS,
    )
    def test_zip_cppa_vectors(
        self, raw: str, expected_std: str, expected_hash: str
    ) -> None:
        assert standardize_zip(raw) == expected_std
        assert hash_std(expected_std) == expected_hash

    def test_dob_cppa_vector(self) -> None:
        raw, expected_std, expected_hash = DOB_VECTOR
        assert standardize_dob(raw) == expected_std
        assert hash_std(expected_std) == expected_hash

    @pytest.mark.parametrize(
        ("raw", "expected_std", "expected_hash"),
        NAME_VECTORS,
    )
    def test_name_cppa_vectors(
        self, raw: str, expected_std: str, expected_hash: str
    ) -> None:
        assert standardize_name(raw) == expected_std
        assert hash_std(expected_std) == expected_hash


class TestInvalidDobReturnsNone:
    @pytest.mark.parametrize(
        "bad_dob",
        [
            "13/40/2020",
            "02/30/2000",
            "Notamonth 4, 1985",
            "Smarch 15, 2001",
        ],
    )
    def test_standardize_dob_invalid_returns_none(self, bad_dob: str) -> None:
        assert standardize_dob(bad_dob) is None

    @pytest.mark.parametrize(
        "bad_dob",
        [
            "13/40/2020",
            "02/30/2000",
            "Notamonth 4, 1985",
        ],
    )
    def test_ndz_hash_skips_invalid_dob(self, bad_dob: str) -> None:
        first, last, _, zip_code = NDZ_INPUT
        assert ndz_hash_from_parts(first, last, bad_dob, zip_code) is None


class TestNdzHashFromParts:
    def test_ndz_cppa_vector(self) -> None:
        first, last, dob, zip_code = NDZ_INPUT
        assert standardize_name(first) == NDZ_FIELD_HASHES["first_name_std"]
        assert standardize_name(last) == NDZ_FIELD_HASHES["last_name_std"]
        assert standardize_dob(dob) == NDZ_FIELD_HASHES["dob_std"]
        assert standardize_zip(zip_code) == NDZ_FIELD_HASHES["zip_std"]
        assert hash_std(NDZ_FIELD_HASHES["first_name_std"]) == NDZ_FIELD_HASHES[
            "first_name_hash"
        ]
        assert hash_std(NDZ_FIELD_HASHES["last_name_std"]) == NDZ_FIELD_HASHES[
            "last_name_hash"
        ]
        assert hash_std(NDZ_FIELD_HASHES["dob_std"]) == NDZ_FIELD_HASHES["dob_hash"]
        assert hash_std(NDZ_FIELD_HASHES["zip_std"]) == NDZ_FIELD_HASHES["zip_hash"]
        assert ndz_hash_from_parts(first, last, dob, zip_code) == NDZ_FINAL_HASH

    def test_ndz_missing_part_returns_none(self) -> None:
        first, last, dob, zip_code = NDZ_INPUT
        assert ndz_hash_from_parts(None, last, dob, zip_code) is None
        assert ndz_hash_from_parts(first, None, dob, zip_code) is None
        assert ndz_hash_from_parts(first, last, None, zip_code) is None
        assert ndz_hash_from_parts(first, last, dob, None) is None
        assert ndz_hash_from_parts(first, last, dob, "") is None


class TestHashedVendorRecord:
    def test_accepts_hashed_fields_only(self) -> None:
        record = HashedVendorRecord(
            system="axios_headquarters",
            vendor_record_id="ax-123",
            email_hash="KA18MT/ph6IHYjzT9zwETySDQyvSh87YuoSBpOQtkhE=",
            extracted_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        )
        assert record.system == "axios_headquarters"
        assert record.vendor_record_id == "ax-123"
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
                system="axios_headquarters",
                vendor_record_id="ax-123",
                email="anna.smith@domain.com",
                extracted_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
            )
