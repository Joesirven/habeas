"""DROP connector settings and sandbox URL guard."""

from __future__ import annotations

from typing import Self

from pydantic import model_validator
from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings

DEFAULT_DROP_API_BASE_URL = "https://api.drop.privacy.ca.gov/sandbox"


class DropConnectorSettings(CoreSettings):
    """Environment-driven settings for the DROP connector worker."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "drop-connector"
    port: int = 8080
    worker_id: str = "drop-connector-dev"

    drop_api_base_url: str = DEFAULT_DROP_API_BASE_URL
    drop_api_key: str = ""
    drop_env: str = "sandbox"
    # ADR-32: required durable ZIP staging (no local disk).
    drop_inbound_bucket: str = "example-gcp-project-drop-inbound-dev"

    @model_validator(mode="after")
    def refuse_non_sandbox_url_when_sandbox_env(self) -> Self:
        if self.drop_env.lower() == "sandbox" and "/sandbox" not in self.drop_api_base_url.lower():
            raise ValueError(
                "DROP_ENV=sandbox requires DROP_API_BASE_URL to contain '/sandbox' "
                f"(got {self.drop_api_base_url!r})"
            )
        return self
