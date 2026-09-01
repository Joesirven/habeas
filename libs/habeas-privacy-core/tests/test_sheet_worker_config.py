"""Tests for SheetWorkerConfig presets and env helpers."""

from __future__ import annotations

from habeas_privacy_core.connections.catalog import VERTICAL_BIZDEV, VERTICAL_PEOPLE_HR
from habeas_privacy_core.queue.constants import (
    BIZDEV_CONTACTS_ATTEMPTS_TABLE,
    HR_ALUMNI_ATTEMPTS_TABLE,
)
from habeas_privacy_core.sheet_worker.config import (
    SheetWorkerConfig,
    bizdev_contacts_config,
    hr_alumni_config,
)


def test_hr_alumni_config_fields() -> None:
    cfg = hr_alumni_config()
    assert cfg.system_id == "hr_alumni"
    assert cfg.attempts_table == HR_ALUMNI_ATTEMPTS_TABLE
    assert cfg.lease_key == "hr_alumni"
    assert cfg.vertical_id == VERTICAL_PEOPLE_HR
    assert cfg.mart_table == "hr_alumni_email_hash__build"
    assert cfg.hashed_raw_table == "hr_alumni_hashed_raw"
    assert cfg.dbt_select == ("stg_hr_alumni_hashed", "mart_hr_alumni_email_hash")
    assert cfg.adapter_label == "sheets_hash"
    assert cfg.env_prefix == "HR_ALUMNI"
    assert cfg.service_name == "hr-alumni"
    assert cfg.default_drain_lease_holder == "hr_alumni-matching-drain"


def test_bizdev_contacts_config_fields() -> None:
    cfg = bizdev_contacts_config()
    assert cfg.system_id == "bizdev_contacts"
    assert cfg.attempts_table == BIZDEV_CONTACTS_ATTEMPTS_TABLE
    assert cfg.lease_key == "bizdev_contacts"
    assert cfg.mart_table == "bizdev_contacts_email_hash__build"
    assert cfg.hashed_raw_table == "bizdev_contacts_hashed_raw"
    assert cfg.env_prefix == "BIZDEV_CONTACTS"


def test_env_var_helper() -> None:
    cfg = hr_alumni_config()
    assert cfg.env_var("DRAIN_JOB_NAME") == "HR_ALUMNI_DRAIN_JOB_NAME"
    assert cfg.env_var("DRAIN_LEASE_HOLDER") == "HR_ALUMNI_DRAIN_LEASE_HOLDER"


def test_config_is_frozen() -> None:
    cfg = hr_alumni_config()
    try:
        cfg.system_id = "other"  # type: ignore[misc]
        raised = False
    except AttributeError:
        raised = True
    assert raised


def test_custom_service_name_override() -> None:
    cfg = SheetWorkerConfig(
        system_id="hr_alumni",
        attempts_table=HR_ALUMNI_ATTEMPTS_TABLE,
        lease_key="hr_alumni",
        vertical_id=VERTICAL_PEOPLE_HR,
        mart_table="hr_alumni_email_hash__build",
        hashed_raw_table="hr_alumni_hashed_raw",
        dbt_select=("stg_hr_alumni_hashed", "mart_hr_alumni_email_hash"),
        adapter_label="sheets_hash",
        env_prefix="HR_ALUMNI",
        service_name="hr-alumni-prod",
    )
    assert cfg.service_name == "hr-alumni-prod"
