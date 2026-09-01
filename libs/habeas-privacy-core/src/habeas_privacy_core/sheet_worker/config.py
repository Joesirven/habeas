"""Configuration for a single-catalog-system Google Sheets worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from habeas_privacy_core.connections.catalog import VERTICAL_BIZDEV, VERTICAL_PEOPLE_HR
from habeas_privacy_core.queue.constants import (
    BIZDEV_CONTACTS_ATTEMPTS_TABLE,
    HR_ALUMNI_ATTEMPTS_TABLE,
)

__all__ = [
    "SheetWorkerConfig",
    "bizdev_contacts_config",
    "hr_alumni_config",
]


@dataclass(frozen=True, slots=True)
class SheetWorkerConfig:
    """Frozen config for one sheet-system Cloud Run worker."""

    system_id: str
    attempts_table: str
    lease_key: str
    vertical_id: str
    mart_table: str
    hashed_raw_table: str
    dbt_select: tuple[str, ...]
    adapter_label: str
    env_prefix: str
    service_name: str = ""
    default_drain_lease_holder: str = ""

    def __post_init__(self) -> None:
        normalized = self.system_id.strip().lower()
        if normalized != self.system_id:
            object.__setattr__(self, "system_id", normalized)
        if not self.service_name:
            object.__setattr__(self, "service_name", normalized.replace("_", "-"))
        if not self.default_drain_lease_holder:
            object.__setattr__(
                self,
                "default_drain_lease_holder",
                f"{normalized}-matching-drain",
            )

    def env_var(self, suffix: str) -> str:
        """Build an environment variable name, e.g. ``HR_ALUMNI_DRAIN_JOB_NAME``."""
        return f"{self.env_prefix}_{suffix}"


def hr_alumni_config() -> SheetWorkerConfig:
    """Preset config for the Alumni sheet worker."""
    return SheetWorkerConfig(
        system_id="hr_alumni",
        attempts_table=HR_ALUMNI_ATTEMPTS_TABLE,
        lease_key="hr_alumni",
        vertical_id=VERTICAL_PEOPLE_HR,
        mart_table="hr_alumni_email_hash__build",
        hashed_raw_table="hr_alumni_hashed_raw",
        dbt_select=("stg_hr_alumni_hashed", "mart_hr_alumni_email_hash"),
        adapter_label="sheets_hash",
        env_prefix="HR_ALUMNI",
    )


def bizdev_contacts_config() -> SheetWorkerConfig:
    """Preset config for the Contact Us sheet worker."""
    return SheetWorkerConfig(
        system_id="bizdev_contacts",
        attempts_table=BIZDEV_CONTACTS_ATTEMPTS_TABLE,
        lease_key="bizdev_contacts",
        vertical_id=VERTICAL_BIZDEV,
        mart_table="bizdev_contacts_email_hash__build",
        hashed_raw_table="bizdev_contacts_hashed_raw",
        dbt_select=("stg_bizdev_contacts_hashed", "mart_bizdev_contacts_email_hash"),
        adapter_label="sheets_hash",
        env_prefix="BIZDEV_CONTACTS",
    )


HR_ALUMNI_CONFIG: Final[SheetWorkerConfig] = hr_alumni_config()
BIZDEV_CONTACTS_CONFIG: Final[SheetWorkerConfig] = bizdev_contacts_config()
