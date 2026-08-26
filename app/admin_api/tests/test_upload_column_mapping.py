"""Upload CSV column auto-bind, remap, success, and failure fixtures."""

from __future__ import annotations

from pathlib import Path

from admin_api.upload_templates import (
    EMAIL_FORMAT_STRICT,
    PHONE_FORMAT_E164,
    parse_upload_csv,
    suggest_column_mapping,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "upload_mapping"

_REMAP = {"first_name": "Given", "last_name": "Family", "email": "Work Email"}


def _bytes(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def test_success_fixture_matches_canonical_headers() -> None:
    ok, detail, stats = parse_upload_csv(
        system="hr_alumni",
        content=_bytes("success.csv"),
        multi_pii_delimiter=None,
    )
    assert ok is True
    assert detail == "upload_ok"
    assert stats["row_count"] == 1
    assert stats["usable_identifier_count"] >= 1


def test_email_only_fixture_succeeds() -> None:
    ok, detail, stats = parse_upload_csv(
        system="axios_headquarters",
        content=_bytes("success_email_only.csv"),
        multi_pii_delimiter=None,
    )
    assert ok is True
    assert detail == "upload_ok"
    assert stats["usable_identifier_count"] == 1


def test_phone_only_fixture_succeeds() -> None:
    ok, detail, stats = parse_upload_csv(
        system="paylocity",
        content=_bytes("success_phone_only.csv"),
        multi_pii_delimiter=None,
    )
    assert ok is True
    assert detail == "upload_ok"
    assert stats["usable_identifier_count"] == 1


def test_names_without_email_are_usable() -> None:
    ok, detail, stats = parse_upload_csv(
        system="bizdev_contacts",
        content=_bytes("failure_missing_email.csv"),
        multi_pii_delimiter=None,
    )
    assert ok is True
    assert detail == "upload_ok"
    assert stats["usable_identifier_count"] >= 1


def test_autobind_fixture_maps_display_aliases_without_user_map() -> None:
    ok, detail, stats = parse_upload_csv(
        system="axios_headquarters",
        content=_bytes("autobind.csv"),
        multi_pii_delimiter=None,
    )
    assert ok is True
    assert detail == "upload_ok"
    assert stats["usable_identifier_count"] >= 1


def test_remap_fixture_needs_mapping_until_user_binds() -> None:
    content = _bytes("remap.csv")
    ok, detail, stats = parse_upload_csv(
        system="bizdev_contacts",
        content=content,
        multi_pii_delimiter=None,
    )
    assert ok is False
    assert detail == "upload_needs_mapping"
    assert "Given" in stats["detected_headers"]

    ok2, detail2, stats2 = parse_upload_csv(
        system="bizdev_contacts",
        content=content,
        multi_pii_delimiter=None,
        column_mapping=_REMAP,
    )
    assert ok2 is True
    assert detail2 == "upload_ok"
    assert stats2["usable_identifier_count"] >= 1


def test_remap_wrong_map_still_fails() -> None:
    ok, detail, _stats = parse_upload_csv(
        system="bizdev_contacts",
        content=_bytes("remap.csv"),
        multi_pii_delimiter=None,
        column_mapping={"email": "Department"},
    )
    assert ok is False
    assert detail == "upload_rows_rejected"


def test_failure_no_identifier_needs_mapping() -> None:
    ok, detail, stats = parse_upload_csv(
        system="paylocity",
        content=_bytes("failure_no_identifier.csv"),
        multi_pii_delimiter=None,
    )
    assert ok is False
    assert detail == "upload_needs_mapping"
    assert stats["detected_header_count"] == 2


def test_failure_no_usable_rows_are_rejected_with_row_indexes() -> None:
    ok, detail, stats = parse_upload_csv(
        system="hr_alumni",
        content=_bytes("failure_no_usable_rows.csv"),
        multi_pii_delimiter=None,
    )
    assert ok is False
    assert detail == "upload_rows_rejected"
    assert stats["row_count"] == 1
    assert stats["rejected_row_count"] == 1
    assert stats["rejected_rows"] == [
        {"row": 1, "codes": ["email_invalid", "phone_invalid"]},
    ]


def test_corrupted_emails_fixture_rejects_each_row() -> None:
    ok, detail, stats = parse_upload_csv(
        system="axios_headquarters",
        content=_bytes("corrupted_emails.csv"),
        multi_pii_delimiter=None,
    )
    assert ok is False
    assert detail == "upload_rows_rejected"
    assert stats["rejected_row_count"] == 3
    assert [item["row"] for item in stats["rejected_rows"]] == [1, 2, 3]
    assert all("email_invalid" in item["codes"] for item in stats["rejected_rows"])


def test_corrupted_phones_fixture_rejects_each_row() -> None:
    ok, detail, stats = parse_upload_csv(
        system="paylocity",
        content=_bytes("corrupted_phones.csv"),
        multi_pii_delimiter=None,
    )
    assert ok is False
    assert detail == "upload_rows_rejected"
    assert stats["rejected_row_count"] == 3
    assert all("phone_invalid" in item["codes"] for item in stats["rejected_rows"])


def test_mixed_good_and_corrupt_keeps_accepted_count_and_indexes() -> None:
    ok, detail, stats = parse_upload_csv(
        system="hr_alumni",
        content=_bytes("mixed_good_and_corrupt.csv"),
        multi_pii_delimiter=None,
    )
    assert ok is False
    assert detail == "upload_rows_rejected"
    assert stats["accepted_row_count"] == 1
    assert stats["rejected_row_count"] == 2
    assert stats["rejected_rows"] == [
        {"row": 2, "codes": ["email_invalid"]},
        {"row": 3, "codes": ["phone_invalid"]},
    ]


def test_e164_phone_format_rejects_unprefixed_us_number() -> None:
    ok, detail, stats = parse_upload_csv(
        system="paylocity",
        content=_bytes("success_phone_only.csv"),
        multi_pii_delimiter=None,
        phone_format=PHONE_FORMAT_E164,
    )
    assert ok is False
    assert detail == "upload_rows_rejected"
    assert stats["rejected_rows"][0]["codes"] == ["phone_invalid"]


def test_strict_email_rejects_single_letter_tld() -> None:
    content = b"email\nuser@example.c\n"
    ok, detail, stats = parse_upload_csv(
        system="axios_headquarters",
        content=content,
        multi_pii_delimiter=None,
        email_format=EMAIL_FORMAT_STRICT,
    )
    assert ok is False
    assert detail == "upload_rows_rejected"
    assert stats["rejected_rows"][0]["codes"] == ["email_invalid"]


def test_invalid_format_code() -> None:
    ok, detail, stats = parse_upload_csv(
        system="axios_headquarters",
        content=_bytes("success_email_only.csv"),
        multi_pii_delimiter=None,
        email_format="not-a-format",
    )
    assert ok is False
    assert detail == "upload_invalid_format"
    assert stats == {}


def test_suggest_column_mapping_autobind_headers() -> None:
    mapping = suggest_column_mapping(
        ["First Name", "Last Name", "Email Address"],
        ("first_name", "last_name", "email"),
    )
    assert mapping == {
        "first_name": "First Name",
        "last_name": "Last Name",
        "email": "Email Address",
    }


def test_stats_never_include_email_values_from_remap_fixture() -> None:
    _ok, _detail, stats = parse_upload_csv(
        system="bizdev_contacts",
        content=_bytes("remap.csv"),
        multi_pii_delimiter=None,
        column_mapping=_REMAP,
    )
    for value in stats.values():
        assert "@" not in str(value)
