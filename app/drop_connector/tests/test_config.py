"""T6.3 — sandbox env refuses production base URL."""

import pytest
from pydantic import ValidationError

from drop_connector.config import DEFAULT_DROP_API_BASE_URL, DropConnectorSettings


def test_sandbox_default_url_accepted():
    settings = DropConnectorSettings(
        drop_api_base_url=DEFAULT_DROP_API_BASE_URL,
        drop_api_key="test-key",
        drop_env="sandbox",
        database_url="",
        _env_file=None,
    )
    assert "/sandbox" in settings.drop_api_base_url


def test_sandbox_refuses_production_url():
    with pytest.raises(ValidationError, match="/sandbox"):
        DropConnectorSettings(
            drop_api_base_url="https://api.drop.privacy.ca.gov",
            drop_api_key="test-key",
            drop_env="sandbox",
            database_url="",
            _env_file=None,
        )


def test_non_sandbox_env_allows_non_sandbox_url():
    settings = DropConnectorSettings(
        drop_api_base_url="https://api.drop.privacy.ca.gov",
        drop_api_key="test-key",
        drop_env="production",
        database_url="",
        _env_file=None,
    )
    assert settings.drop_env == "production"
