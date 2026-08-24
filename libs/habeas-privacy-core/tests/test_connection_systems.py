"""Tests for per-system connection credential schemas."""

from __future__ import annotations

import pytest

from habeas_privacy_core.connections.catalog import (
    APPROACH_LIVE,
    APPROACH_UPLOAD,
    CATALOG_BINDINGS,
    CATALOG_VERTICALS,
    UPLOAD_TEMPLATE_OPTIONAL_HEADERS,
    UPLOAD_TEMPLATE_REQUIRED_HEADERS,
    VERTICAL_BIZDEV,
    VERTICAL_DATA,
    VERTICAL_PEOPLE_HR,
    get_bindings_for_system,
    get_bindings_for_vertical,
    get_vertical,
    is_approach_allowed,
    list_verticals,
)
from habeas_privacy_core.connections.systems import (
    SYSTEM_IDS,
    CredentialInputType,
    get_system,
    list_systems,
    validate_credentials,
)

_EXPECTED_ORDER = (
    "mailchimp",
    "paylocity",
    "lever",
    "auth0",
    "google_sheets",
    "bizdev_contacts",
    "hr_alumni",
    "cassandra",
)

_INVITE_ALLOWED_SYSTEMS = frozenset(
    {
        "mailchimp",
        "paylocity",
        "lever",
        "auth0",
    }
)


class TestCatalog:
    def test_system_ids_contains_all_systems(self) -> None:
        assert SYSTEM_IDS == frozenset(_EXPECTED_ORDER)

    def test_list_systems_stable_order(self) -> None:
        systems = list_systems()
        assert [system.system_id for system in systems] == list(_EXPECTED_ORDER)

    def test_get_system_returns_definition(self) -> None:
        system = get_system("mailchimp")
        assert system.display_label == "Mailchimp"
        assert system.invite_allowed is True
        assert len(system.credential_fields) == 1
        assert system.credential_fields[0].id == "api_key"

    def test_get_system_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown connection system"):
            get_system("vertica")


class TestVerticalCatalog:
    def test_catalog_vertical_ids_match_seed(self) -> None:
        assert [entry.vertical_id for entry in CATALOG_VERTICALS] == [
            "communications",
            "people_hr",
            "tech",
            "bizdev",
            "data",
        ]

    def test_data_vertical_is_view_only(self) -> None:
        data = get_vertical(VERTICAL_DATA)
        assert data.view_only is True
        assert data.display_label == "Data"

    def test_people_hr_bindings(self) -> None:
        bindings = {binding.system: binding for binding in get_bindings_for_vertical(VERTICAL_PEOPLE_HR)}
        assert set(bindings) == {"paylocity", "lever", "hr_alumni"}
        assert bindings["hr_alumni"].allowed_approaches == frozenset({APPROACH_UPLOAD})
        assert bindings["paylocity"].allowed_approaches == frozenset({APPROACH_UPLOAD, APPROACH_LIVE})

    def test_bizdev_upload_only_binding(self) -> None:
        bindings = get_bindings_for_vertical(VERTICAL_BIZDEV)
        assert len(bindings) == 1
        assert bindings[0].system == "bizdev_contacts"
        assert bindings[0].allowed_approaches == frozenset({APPROACH_UPLOAD})

    def test_is_approach_allowed(self) -> None:
        assert is_approach_allowed("tech", "auth0", APPROACH_LIVE) is True
        assert is_approach_allowed("bizdev", "bizdev_contacts", APPROACH_LIVE) is False
        assert is_approach_allowed("data", "cassandra", APPROACH_UPLOAD) is False

    def test_get_bindings_for_system(self) -> None:
        mailchimp_bindings = get_bindings_for_system("mailchimp")
        assert len(mailchimp_bindings) == 1
        assert mailchimp_bindings[0].vertical_id == "communications"

    def test_list_verticals_sorted(self) -> None:
        verticals = list_verticals()
        assert [entry.sort_order for entry in verticals] == sorted(entry.sort_order for entry in verticals)

    def test_catalog_bindings_count(self) -> None:
        assert len(CATALOG_BINDINGS) == 7


class TestUploadSystems:
    def test_bizdev_contacts_upload_only(self) -> None:
        system = get_system("bizdev_contacts")
        assert system.invite_allowed is False
        assert system.credential_fields == ()
        assert "Upload mode only" in system.trust_copy

    def test_hr_alumni_upload_only(self) -> None:
        system = get_system("hr_alumni")
        assert system.invite_allowed is False
        assert system.credential_fields == ()
        assert validate_credentials(system, {}) == {}

    def test_upload_template_headers(self) -> None:
        assert UPLOAD_TEMPLATE_REQUIRED_HEADERS["bizdev_contacts"] == (
            "first_name",
            "last_name",
            "email",
        )
        assert "phone" in UPLOAD_TEMPLATE_OPTIONAL_HEADERS["hr_alumni"]
        assert "employee_id" in UPLOAD_TEMPLATE_OPTIONAL_HEADERS["paylocity"]


class TestInvitePolicy:
    def test_cassandra_disallows_invites(self) -> None:
        cassandra = get_system("cassandra")
        assert cassandra.invite_allowed is False
        assert cassandra.credential_fields == ()

    def test_google_sheets_invite_retired(self) -> None:
        sheets = get_system("google_sheets")
        assert sheets.invite_allowed is False

    def test_upload_systems_disallow_invites(self) -> None:
        assert get_system("bizdev_contacts").invite_allowed is False
        assert get_system("hr_alumni").invite_allowed is False

    @pytest.mark.parametrize("system_id", sorted(_INVITE_ALLOWED_SYSTEMS))
    def test_invite_allowed_systems(self, system_id: str) -> None:
        assert get_system(system_id).invite_allowed is True

    def test_lever_help_requires_users_read_list(self) -> None:
        system = get_system("lever")
        field = system.credential_fields[0]
        assert field.help is not None
        assert "Users read/list" in field.help
        assert "Postings" in field.help
        assert "Users read/list" in system.trust_copy


class TestFieldSchemas:
    def test_paylocity_fields(self) -> None:
        fields = {field.id: field for field in get_system("paylocity").credential_fields}
        assert set(fields) == {"client_id", "client_secret", "company_id", "environment"}
        assert fields["client_secret"].input_type is CredentialInputType.PASSWORD
        assert fields["company_id"].input_type is CredentialInputType.TEXT
        assert fields["environment"].required is True

    def test_paylocity_trust_copy_documents_upload_and_live(self) -> None:
        copy = get_system("paylocity").trust_copy
        assert "Upload mode" in copy
        assert "Live mode" in copy
        assert "SFTP" in copy

    def test_auth0_fields(self) -> None:
        fields = {field.id: field for field in get_system("auth0").credential_fields}
        assert set(fields) == {"domain", "client_id", "client_secret"}

    def test_google_sheets_url_field_help(self) -> None:
        field = get_system("google_sheets").credential_fields[0]
        assert field.id == "spreadsheet_url"
        assert field.input_type is CredentialInputType.URL
        assert field.help is not None
        assert "95660886550-compute@developer.gserviceaccount.com" in field.help
        assert "Editor" in field.help
        assert "suppression" in field.help.lower()
        assert "from your invite page" not in field.help.lower()
        assert "json" in field.help.lower()
        assert "Viewer" not in field.help

    def test_google_sheets_help_respects_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "GOOGLE_SHEETS_SHARE_SERVICE_ACCOUNT",
            "sheets-share@example.iam.gserviceaccount.com",
        )
        field = get_system("google_sheets").credential_fields[0]
        assert field.help is not None
        assert "sheets-share@example.iam.gserviceaccount.com" in field.help
        assert "Editor" in field.help

    def test_trust_copy_mentions_secret_manager(self) -> None:
        mailchimp = get_system("mailchimp")
        assert "Secret Manager" in mailchimp.trust_copy
        assert "application database" in mailchimp.trust_copy.lower()
        assert "72 hours" in mailchimp.trust_copy

    def test_cassandra_trust_copy_is_inf_handoff(self) -> None:
        copy = get_system("cassandra").trust_copy
        assert "INF" in copy or "Infrastructure" in copy
        assert "infra_pending" in copy


class TestValidateCredentials:
    def test_mailchimp_accepts_api_key(self) -> None:
        system = get_system("mailchimp")
        cleaned = validate_credentials(system, {"api_key": "  mc-key-123  "})
        assert cleaned == {"api_key": "mc-key-123"}

    def test_paylocity_requires_all_fields(self) -> None:
        system = get_system("paylocity")
        with pytest.raises(ValueError, match="missing required credential field: client_secret"):
            validate_credentials(
                system,
                {"client_id": "cid", "company_id": "co-1"},
            )

    def test_google_sheets_validates_url(self) -> None:
        system = get_system("google_sheets")
        cleaned = validate_credentials(
            system,
            {"spreadsheet_url": "https://docs.google.com/spreadsheets/d/abc123/edit"},
        )
        assert cleaned["spreadsheet_url"].startswith("https://")

        with pytest.raises(ValueError, match="must be a valid http or https URL"):
            validate_credentials(system, {"spreadsheet_url": "not-a-url"})

    def test_unknown_fields_rejected(self) -> None:
        system = get_system("lever")
        with pytest.raises(ValueError, match="unknown credential fields"):
            validate_credentials(system, {"api_key": "x", "extra": "y"})

    def test_empty_required_field_rejected(self) -> None:
        system = get_system("lever")
        with pytest.raises(ValueError, match="missing required credential field: api_key"):
            validate_credentials(system, {"api_key": "   "})

    def test_cassandra_rejects_any_credentials(self) -> None:
        system = get_system("cassandra")
        assert validate_credentials(system, {}) == {}
        with pytest.raises(ValueError, match="does not accept credentials via invite"):
            validate_credentials(system, {"api_key": "nope"})

    def test_upload_systems_reject_credentials(self) -> None:
        for system_id in ("bizdev_contacts", "hr_alumni"):
            system = get_system(system_id)
            with pytest.raises(ValueError, match="does not accept credentials via invite"):
                validate_credentials(system, {"api_key": "nope"})

    def test_non_string_value_rejected(self) -> None:
        system = get_system("mailchimp")
        with pytest.raises(ValueError, match="must be a string"):
            validate_credentials(system, {"api_key": 123})  # type: ignore[arg-type]
