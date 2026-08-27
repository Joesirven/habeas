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
    # Coalesce window for drop_bulk_stats_changed NOTIFY fan-out (admin-api live SSE).
    live_bulk_notify_coalesce_ms: int = 200
