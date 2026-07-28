"""Data fulfillment dispatcher settings."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings


class DataFulfillmentDispatcherSettings(CoreSettings):
    """Environment-driven settings for the DROP fulfillment stub worker."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "data-fulfillment-dispatcher"
    port: int = 8080
    worker_id: str = "data-fulfillment-dispatcher-dev"
    fulfill_batch_size: int = 100
    # Dedicated fulfillment artifact bucket (separate from DROP intake staging).
    fulfillment_gcs_bucket: str = ""
    # BigQuery source for access reproduction exports. Defaults to raw
    # person_db mirrors; flip dataset/tables to the transform/access_export
    # dbt marts (KTD-13) without a code change.
    access_export_bq_project: str = "example-gcp-project"
    access_export_bq_dataset: str = "person_db"
    # Comma-separated table override; empty uses ACCESS_TABLE_ALLOWLIST.
    access_export_bq_tables: str = ""

    def access_export_tables(self) -> tuple[str, ...]:
        return tuple(
            name.strip()
            for name in self.access_export_bq_tables.split(",")
            if name.strip()
        )

