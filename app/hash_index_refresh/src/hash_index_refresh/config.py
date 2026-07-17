"""Hash index refresh worker settings."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings


class HashIndexRefreshSettings(CoreSettings):
    """Environment-driven settings for the hash index refresh worker."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "hash-index-refresh"
    port: int = 8080
    worker_id: str = "hash-index-refresh-dev"
    drop_hash_dbt_dir: str = "transform/drop_hash"
    dbt_timeout_seconds: int = 3600
    claim_lease_minutes: int = 120


def resolve_dbt_dir(raw_path: str) -> Path:
    """Resolve the dbt project directory from env or default."""
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()
