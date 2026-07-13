"""Environment-driven settings base for apps."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    """Shared settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "data-privacy"
    database_url: str = ""
    log_level: str = "INFO"
    gcp_project: str | None = None
    enable_cloud_trace: bool = True
