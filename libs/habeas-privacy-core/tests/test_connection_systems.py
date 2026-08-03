"""Tests for per-system connection credential schemas."""

from __future__ import annotations

import pytest

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
    "cassandra",
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


class TestInvitePolicy:
    def test_cassandra_disallows_invites(self) -> None:
        cassandra = get_system("cassandra")
        assert cassandra.invite_allowed is False
        assert cassandra.credential_fields == ()

    @pytest.mark.parametrize("system_id", _EXPECTED_ORDER[:-1])
    def test_saas_systems_allow_invites(self, system_id: str) -> None:
        assert get_system(system_id).invite_allowed is True


class TestFieldSchemas:
    def test_paylocity_fields(self) -> None:
        fields = {field.id: field for field in get_system("paylocity").credential_fields}
        assert set(fields) == {"client_id", "client_secret", "company_id", "environment"}
        assert fields["client_secret"].input_type is CredentialInputType.PASSWORD
        assert fields["company_id"].input_type is CredentialInputType.TEXT
        assert fields["environment"].required is True

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

    def test_non_string_value_rejected(self) -> None:
        system = get_system("mailchimp")
        with pytest.raises(ValueError, match="must be a string"):
            validate_credentials(system, {"api_key": 123})  # type: ignore[arg-type]
