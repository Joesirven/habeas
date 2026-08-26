"""Tests for per-system connection credential schemas."""

from __future__ import annotations

import pytest

from habeas_privacy_core.connections.catalog import (
    APPROACH_LIVE,
    APPROACH_UPLOAD,
    CATALOG_BINDINGS,
    CATALOG_VERTICALS,
    UPLOAD_ONLY_SYSTEMS,
    UPLOAD_SYSTEMS,
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
    "paylocity",
    "lever",
    "auth0",
    "google_sheets",
    "alumni_google_sheet",
    "contact_us_google_sheet",
    "bizdev_contacts",
    "hr_alumni",
    "axios_headquarters",
    "cassandra",
)

_INVITE_ALLOWED_SYSTEMS = frozenset(
    {
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
        system = get_system("axios_headquarters")
        assert system.display_label == "Axios HQ"
        assert system.invite_allowed is False
        assert system.credential_fields == ()

    def test_axios_hq_is_not_a_duplicate_system(self) -> None:
        # Web/session may use axios_hq; remaining-ops alias (not a second catalog entry).
        assert "axios_hq" not in SYSTEM_IDS
        with pytest.raises(ValueError, match="unknown connection system"):
            get_system("axios_hq")

    def test_get_system_mailchimp_is_not_live(self) -> None:
        assert "mailchimp" not in SYSTEM_IDS
        with pytest.raises(ValueError, match="unknown connection system"):
            get_system("mailchimp")

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
            "test",
        ]

    def test_data_vertical_is_view_only(self) -> None:
        data = get_vertical(VERTICAL_DATA)
        assert data.view_only is True
        assert data.display_label == "Data"

    def test_communications_upload_only_binding(self) -> None:
        bindings = get_bindings_for_vertical("communications")
        assert len(bindings) == 1
        assert bindings[0].system == "axios_headquarters"
        assert bindings[0].allowed_approaches == frozenset({APPROACH_UPLOAD})

    def test_people_hr_bindings(self) -> None:
        bindings = {binding.system: binding for binding in get_bindings_for_vertical(VERTICAL_PEOPLE_HR)}
        assert set(bindings) == {"paylocity", "lever", "hr_alumni"}
        assert bindings["hr_alumni"].allowed_approaches == frozenset(
            {APPROACH_UPLOAD, APPROACH_LIVE}
        )
        assert bindings["paylocity"].allowed_approaches == frozenset({APPROACH_UPLOAD, APPROACH_LIVE})
        assert bindings["lever"].allowed_approaches == frozenset({APPROACH_UPLOAD, APPROACH_LIVE})
        assert APPROACH_LIVE in bindings["lever"].allowed_approaches

    def test_bizdev_upload_or_live_binding(self) -> None:
        bindings = get_bindings_for_vertical(VERTICAL_BIZDEV)
        assert {b.system for b in bindings} == {"bizdev_contacts"}
        assert bindings[0].allowed_approaches == frozenset({APPROACH_UPLOAD, APPROACH_LIVE})

    def test_is_approach_allowed(self) -> None:
        assert is_approach_allowed("tech", "auth0", APPROACH_LIVE) is True
        assert is_approach_allowed("bizdev", "bizdev_contacts", APPROACH_LIVE) is True
        assert is_approach_allowed("bizdev", "bizdev_contacts", APPROACH_UPLOAD) is True
        assert is_approach_allowed("people_hr", "hr_alumni", APPROACH_LIVE) is True
        assert is_approach_allowed("people_hr", "hr_alumni", APPROACH_UPLOAD) is True
        assert is_approach_allowed("people_hr", "lever", APPROACH_LIVE) is True
        assert is_approach_allowed("people_hr", "lever", APPROACH_UPLOAD) is True
        assert is_approach_allowed("data", "cassandra", APPROACH_UPLOAD) is False

    def test_get_bindings_for_system(self) -> None:
        assert get_bindings_for_system("mailchimp") == []
        axios_bindings = get_bindings_for_system("axios_headquarters")
        assert len(axios_bindings) == 1
        assert axios_bindings[0].vertical_id == "communications"

    def test_list_verticals_sorted(self) -> None:
        verticals = list_verticals()
        assert [entry.sort_order for entry in verticals] == sorted(entry.sort_order for entry in verticals)

    def test_catalog_bindings_count(self) -> None:
        assert len(CATALOG_BINDINGS) == 9


class TestUploadSystems:
    def test_axios_headquarters_upload_only(self) -> None:
        system = get_system("axios_headquarters")
        assert system.invite_allowed is False
        assert system.credential_fields == ()
        assert "Upload mode only" in system.trust_copy
        assert "every batch" in system.trust_copy
        assert "API keys" in system.trust_copy
        assert "Axios HQ" in system.trust_copy
        assert UPLOAD_ONLY_SYSTEMS == frozenset({"axios_headquarters"})

    def test_bizdev_contacts_upload_or_live_oauth(self) -> None:
        system = get_system("bizdev_contacts")
        assert system.invite_allowed is False
        assert system.credential_fields == ()
        assert "bizdev_contacts" not in UPLOAD_ONLY_SYSTEMS
        assert "Connect Google" in system.trust_copy
        assert "Upload CSV alternative" in system.trust_copy
        assert "service account" in system.trust_copy
        assert "Upload mode only" not in system.trust_copy

    def test_hr_alumni_upload_or_live_oauth(self) -> None:
        system = get_system("hr_alumni")
        assert system.invite_allowed is False
        assert system.credential_fields == ()
        assert "hr_alumni" not in UPLOAD_ONLY_SYSTEMS
        assert "Connect Google" in system.trust_copy
        assert "Upload CSV alternative" in system.trust_copy
        assert "service account" in system.trust_copy
        assert "Upload mode only" not in system.trust_copy
        assert validate_credentials(system, {}) == {}

    def test_lever_upload_fallback_not_upload_only(self) -> None:
        assert "lever" in UPLOAD_SYSTEMS
        assert "lever" not in UPLOAD_ONLY_SYSTEMS
        assert is_approach_allowed("people_hr", "lever", APPROACH_UPLOAD) is True
        assert is_approach_allowed("people_hr", "lever", APPROACH_LIVE) is True

    def test_upload_template_headers(self) -> None:
        assert UPLOAD_TEMPLATE_REQUIRED_HEADERS["axios_headquarters"] == (
            "first_name",
            "last_name",
            "email",
        )
        assert "submitted_at" in UPLOAD_TEMPLATE_OPTIONAL_HEADERS["axios_headquarters"]
        assert UPLOAD_TEMPLATE_REQUIRED_HEADERS["bizdev_contacts"] == (
            "first_name",
            "last_name",
            "email",
        )
        assert "phone" in UPLOAD_TEMPLATE_OPTIONAL_HEADERS["hr_alumni"]
        assert "employee_id" in UPLOAD_TEMPLATE_OPTIONAL_HEADERS["paylocity"]
        assert UPLOAD_TEMPLATE_REQUIRED_HEADERS["lever"] == (
            "first_name",
            "last_name",
            "email",
        )
        assert UPLOAD_TEMPLATE_REQUIRED_HEADERS["lever"] == UPLOAD_TEMPLATE_REQUIRED_HEADERS[
            "paylocity"
        ]
        assert "lever" not in UPLOAD_TEMPLATE_OPTIONAL_HEADERS


class TestInvitePolicy:
    def test_cassandra_disallows_invites(self) -> None:
        cassandra = get_system("cassandra")
        assert cassandra.invite_allowed is False
        assert cassandra.credential_fields == ()

    def test_google_sheets_invite_retired(self) -> None:
        sheets = get_system("google_sheets")
        assert sheets.invite_allowed is False

    def test_upload_systems_disallow_invites(self) -> None:
        assert get_system("axios_headquarters").invite_allowed is False
        assert get_system("bizdev_contacts").invite_allowed is False
        assert get_system("hr_alumni").invite_allowed is False

    @pytest.mark.parametrize("system_id", sorted(_INVITE_ALLOWED_SYSTEMS))
    def test_invite_allowed_systems(self, system_id: str) -> None:
        assert get_system(system_id).invite_allowed is True

    def test_lever_help_requires_users_read_list(self) -> None:
        system = get_system("lever")
        field = system.credential_fields[0]
        assert field.id == "api_key"
        assert tuple(f.id for f in system.credential_fields) == ("api_key",)
        assert field.help is not None
        assert "Users read/list" in field.help
        assert "Postings" in field.help
        assert "does not extract candidates" in field.help
        assert "Users read/list" in system.trust_copy
        assert "probe" in system.trust_copy.lower()
        assert "does not extract candidates" in system.trust_copy
        assert "upload a csv" in system.trust_copy.lower()
        assert "/v1/opportunities" not in system.trust_copy
        assert "/v1/opportunities" not in (field.help or "")


class TestFieldSchemas:
    def test_paylocity_fields(self) -> None:
        fields = {field.id: field for field in get_system("paylocity").credential_fields}
        assert set(fields) == {
            "host",
            "port",
            "directory",
            "username",
            "auth_method",
            "password",
            "private_key",
        }
        assert fields["password"].input_type is CredentialInputType.PASSWORD
        assert fields["private_key"].input_type is CredentialInputType.PASSWORD
        assert fields["host"].required is True
        assert fields["port"].required is True
        assert fields["username"].required is True
        assert fields["auth_method"].required is True
        assert fields["directory"].required is False
        assert "client_id" not in fields
        assert "client_secret" not in fields
        assert "company_id" not in fields
        assert "environment" not in fields

    def test_paylocity_trust_copy_documents_upload_and_live(self) -> None:
        copy = get_system("paylocity").trust_copy
        assert "Upload mode" in copy
        assert "Live mode" in copy
        assert "SFTP" in copy
        assert "does not extract candidate emails" in copy
        assert "Matching uses Upload" in copy
        assert "listdir" not in copy.lower()

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
        paylocity = get_system("paylocity")
        assert "Secret Manager" in paylocity.trust_copy
        assert "application database" in paylocity.trust_copy.lower()
        assert "72 hours" in paylocity.trust_copy

    def test_cassandra_trust_copy_is_inf_handoff(self) -> None:
        copy = get_system("cassandra").trust_copy
        assert "INF" in copy or "Infrastructure" in copy
        assert "infra_pending" in copy
        assert "suppress-only" in copy
        assert "no matching" in copy.lower()
        assert "hash extract" in copy.lower()
        assert "mapping" in copy.lower()


class TestValidateCredentials:
    def test_paylocity_requires_all_fields(self) -> None:
        system = get_system("paylocity")
        with pytest.raises(ValueError, match="missing required credential field: host"):
            validate_credentials(
                system,
                {
                    "port": "22",
                    "username": "sftp-user",
                    "auth_method": "password",
                    "password": "x",
                },
            )

    def test_paylocity_password_auth_requires_password(self) -> None:
        system = get_system("paylocity")
        with pytest.raises(ValueError, match="missing required credential field: password"):
            validate_credentials(
                system,
                {
                    "host": "sftp.example.com",
                    "port": "22",
                    "username": "sftp-user",
                    "auth_method": "password",
                },
            )

    def test_paylocity_port_must_be_22(self) -> None:
        system = get_system("paylocity")
        with pytest.raises(ValueError, match="credential field port must be 22"):
            validate_credentials(
                system,
                {
                    "host": "sftp.example.com",
                    "port": "2222",
                    "username": "sftp-user",
                    "auth_method": "password",
                    "password": "x",
                },
            )

    def test_paylocity_rejects_rest_oauth_fields(self) -> None:
        system = get_system("paylocity")
        with pytest.raises(ValueError, match="unknown credential fields"):
            validate_credentials(
                system,
                {
                    "host": "sftp.example.com",
                    "port": "22",
                    "username": "sftp-user",
                    "auth_method": "password",
                    "password": "x",
                    "client_id": "cid",
                },
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
        for system_id in ("axios_headquarters", "bizdev_contacts", "hr_alumni"):
            system = get_system(system_id)
            with pytest.raises(ValueError, match="does not accept credentials via invite"):
                validate_credentials(system, {"api_key": "nope"})

    def test_non_string_value_rejected(self) -> None:
        system = get_system("lever")
        with pytest.raises(ValueError, match="must be a string"):
            validate_credentials(system, {"api_key": 123})  # type: ignore[arg-type]
