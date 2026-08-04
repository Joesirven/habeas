"""Shared external-hash refresh settings for vertical workers."""

from __future__ import annotations

from pathlib import Path

from habeas_privacy_core.vertical_hash.worker import VerticalHashRefreshConfig

__all__ = ["default_external_hash_dbt_dir", "vertical_hash_refresh_config_from_env"]


def default_external_hash_dbt_dir(*, from_file: str) -> str:
    """Resolve transform/external_hash from a worker main module path."""
    return str(Path(from_file).resolve().parents[4] / "transform" / "external_hash")


def vertical_hash_refresh_config_from_env(
    settings,
    *,
    from_file: str,
) -> VerticalHashRefreshConfig:
    """Build refresh config from a worker Settings object (CoreSettings fields)."""
    return VerticalHashRefreshConfig(
        bq_project=getattr(settings, "external_hash_bq_project", None)
        or settings.gcp_project
        or "example-gcp-project",
        bq_dataset=getattr(settings, "external_hash_bq_dataset", "external_hash_index"),
        dbt_dir=getattr(
            settings,
            "external_hash_dbt_dir",
            default_external_hash_dbt_dir(from_file=from_file),
        ),
        dbt_timeout_seconds=int(
            getattr(settings, "external_hash_dbt_timeout_seconds", 1800)
        ),
        skip_dbt=bool(getattr(settings, "external_hash_skip_dbt", False)),
        skip_bq=bool(getattr(settings, "external_hash_skip_bq", False)),
        lease_minutes=int(getattr(settings, "external_hash_lease_minutes", 60)),
    )
