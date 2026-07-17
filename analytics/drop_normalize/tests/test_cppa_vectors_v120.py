"""Official CPPA DROP v1.2.0 golden vectors."""

from __future__ import annotations

import pytest

from drop_normalize import (
    hash_std,
    ndz_concatenated_hash,
    ndz_field_hashes,
    normalize_dob,
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_zip,
)

# --- Email ---

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

# --- Phone ---

PHONE_VECTORS = [
    ("+1(415)555-9317", "4155559317", "vGM7y5n+hBXRSEAklhHDPCbysyNgYTmXdMcagGUOY8E="),
    ("+84(90)123 4567", "4901234567", "ptzVkgbv9DonwvPCHmXmJ2SEOaolSh37z3ZzY/Gmm+U="),
    ("+354(123)4567", "3541234567", "Btrzydf5K6ALAKKXJGFHSx7u5bDzHC9WlVYtpq1n2rY="),
    ("5551273811", "5551273811", "jr/RAWYVN+ODBf2vRxwBASPwiO4x27OGI1y3IDhcwLo="),
]

# --- ZIP ---

ZIP_VECTORS = [
    ("91790-3771", "91790", "2FPZucR4x7U8KlM+SFAX4LPGhwNz/PIZUCSUdDh0o/s="),
    ("M1B 1A1", "m1b1a", "n8L9q8mVeT6Xt9/EeUNiTukGDrkbPJ3DvOEx14uElxk="),
    (" 00712345", "71234", "aeNUYKh7Xw5sqpxSbSP9eOHsj6iXewbUyavv89DIuhQ="),
    (" 00300-9999", "300", "mDvWFLta/s5as7YCP3EUfNe2vCMU+dJ690IlQcZVg4k="),
]

# --- DOB ---

DOB_VECTOR = (
    "July 4, 1776",
    "17760704",
    "skXYXxBER6HQTZ3rXSZH1wVGLQ054mS5rbR/bwvzy4I=",
)

# --- Names ---

NAME_VECTORS = [
    ("Juan Pablo", "juanpablo", "91hIbrbzNeqHs3o81O5yNrXUj7wDd2shvZ6THKi9qz8="),
    ("Martinez", "martinez", "2wRPGbwBNxhShjRczx8GfS2c4cjvs4NJskeWloUNtp8="),
]

# --- NDZ composite (Danielle Johnson) ---

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


class TestEmailVectors:
    @pytest.mark.parametrize(
        ("raw", "expected_std", "expected_hash"),
        [EMAIL_VECTOR, EMAIL_VECTOR_2],
    )
    def test_email(self, raw: str, expected_std: str, expected_hash: str) -> None:
        assert normalize_email(raw) == expected_std
        assert hash_std(expected_std) == expected_hash


class TestPhoneVectors:
    @pytest.mark.parametrize(
        ("raw", "expected_std", "expected_hash"),
        PHONE_VECTORS,
    )
    def test_phone(self, raw: str, expected_std: str, expected_hash: str) -> None:
        assert normalize_phone(raw) == expected_std
        assert hash_std(expected_std) == expected_hash


class TestZipVectors:
    @pytest.mark.parametrize(
        ("raw", "expected_std", "expected_hash"),
        ZIP_VECTORS,
    )
    def test_zip(self, raw: str, expected_std: str, expected_hash: str) -> None:
        assert normalize_zip(raw) == expected_std
        assert hash_std(expected_std) == expected_hash


class TestDobVector:
    def test_dob(self) -> None:
        raw, expected_std, expected_hash = DOB_VECTOR
        assert normalize_dob(raw) == expected_std
        assert hash_std(expected_std) == expected_hash


class TestNameVectors:
    @pytest.mark.parametrize(
        ("raw", "expected_std", "expected_hash"),
        NAME_VECTORS,
    )
    def test_name(self, raw: str, expected_std: str, expected_hash: str) -> None:
        assert normalize_name(raw) == expected_std
        assert hash_std(expected_std) == expected_hash


class TestNdzVector:
    def test_ndz_field_hashes(self) -> None:
        first, last, dob, zip_code = NDZ_INPUT
        fields = ndz_field_hashes(first, last, dob, zip_code)
        for key, expected in NDZ_FIELD_HASHES.items():
            assert fields[key] == expected, key

    def test_ndz_final_hash(self) -> None:
        first, last, dob, zip_code = NDZ_INPUT
        assert ndz_concatenated_hash(first, last, dob, zip_code) == NDZ_FINAL_HASH

    def test_ndz_concatenation_intermediate(self) -> None:
        first, last, dob, zip_code = NDZ_INPUT
        fields = ndz_field_hashes(first, last, dob, zip_code)
        concatenated = (
            fields["first_name_hash"]
            + fields["last_name_hash"]
            + fields["dob_hash"]
            + fields["zip_hash"]
        )
        expected_concat = (
            "5dUD1FgiKcTJq+JQ5JZUdlyIXrSbtJ338YYbt5/HNG4="
            "K+TjOqPiH2/3rRRPj9WCKKHM47UDQLSAX/DGNIDuxIg="
            "IWi7qxOAbBJe0fNciDj76Eg84gmj40rB7aNMK/VnFOI="
            "2FPZucR4x7U8KlM+SFAX4LPGhwNz/PIZUCSUdDh0o/s="
        )
        assert concatenated == expected_concat
        assert hash_std(concatenated) == NDZ_FINAL_HASH
