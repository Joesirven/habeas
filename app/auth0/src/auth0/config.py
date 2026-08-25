"""Auth0 worker settings — environment only; no secrets in this file."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_EXTERNAL_HASH_DBT_DIR = _REPO_ROOT / "transform" / "external_hash"


class Auth0Settings(CoreSettings):
    """Env-driven worker settings. ``GCP_PROJECT`` is inherited from CoreSettings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "auth0"
    port: int = 8080
    worker_id: str = "auth0-dev"

    auth0_connection_id: str | None = None
    external_hash_dbt_dir: str = str(_DEFAULT_EXTERNAL_HASH_DBT_DIR)
    bq_dataset: str = "external_hash_index"
    hashed_raw_table: str = "auth0_hashed_raw"
    dbt_timeout_seconds: int = 3600
    skip_external_hash_dbt: bool = False
    hash_refresh_lease_minutes: int = 60

    @property
    def hashed_raw_table_id(self) -> str:
        """BigQuery table id for hashed-raw writes (no credentials)."""
        if self.gcp_project:
            return f"{self.gcp_project}.{self.bq_dataset}.{self.hashed_raw_table}"
        return self.hashed_raw_table


settings = Auth0Settings()
