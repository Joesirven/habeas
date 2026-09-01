"""Shared primitives for single-catalog-system Google Sheets workers."""

from habeas_privacy_core.sheet_worker.app import (
    SheetWorkerSettings,
    create_sheet_worker_app,
)
from habeas_privacy_core.sheet_worker.chunk_drain import (
    ChunkDrainModule,
    build_chunk_drain_module,
    claim_matching_chunk,
    complete_matching_attempts,
    ensure_drain,
    process_matching_chunk,
    run_drain_budget,
    run_job_task,
    start_drain_job_execution,
)
from habeas_privacy_core.sheet_worker.config import (
    BIZDEV_CONTACTS_CONFIG,
    HR_ALUMNI_CONFIG,
    SheetWorkerConfig,
    bizdev_contacts_config,
    hr_alumni_config,
)
from habeas_privacy_core.sheet_worker.dbt_runner import DbtRunResult, run_external_hash_dbt_build
from habeas_privacy_core.sheet_worker.error_policy import SheetWorkerErrorClassifier
from habeas_privacy_core.sheet_worker.hash_extract import (
    HashExtractError,
    load_connection_gcs_uri,
    load_connection_upload,
    run_hash_extract,
)
from habeas_privacy_core.sheet_worker.vertical_match import (
    SheetHashLookupError,
    VerticalMatchOutcome,
    lookup_vendor_ids_by_email_hash,
    lookup_vendor_ids_by_email_hashes,
    run_vertical_match,
)

__all__ = [
    "BIZDEV_CONTACTS_CONFIG",
    "ChunkDrainModule",
    "DbtRunResult",
    "HR_ALUMNI_CONFIG",
    "HashExtractError",
    "SheetHashLookupError",
    "SheetWorkerConfig",
    "SheetWorkerErrorClassifier",
    "SheetWorkerSettings",
    "VerticalMatchOutcome",
    "bizdev_contacts_config",
    "build_chunk_drain_module",
    "claim_matching_chunk",
    "complete_matching_attempts",
    "create_sheet_worker_app",
    "ensure_drain",
    "hr_alumni_config",
    "load_connection_gcs_uri",
    "load_connection_upload",
    "lookup_vendor_ids_by_email_hash",
    "lookup_vendor_ids_by_email_hashes",
    "process_matching_chunk",
    "run_drain_budget",
    "run_external_hash_dbt_build",
    "run_hash_extract",
    "run_job_task",
    "run_vertical_match",
    "start_drain_job_execution",
]
