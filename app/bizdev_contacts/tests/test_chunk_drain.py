"""Chunk drain config — attempts table and lease key for Contact Us only."""

from __future__ import annotations

from habeas_privacy_core.queue.constants import BIZDEV_CONTACTS_ATTEMPTS_TABLE
from habeas_privacy_core.sheet_worker.chunk_drain import (
    build_chunk_drain_module,
    claim_matching_chunk_sql,
)
from bizdev_contacts.main import CONFIG


def test_config_uses_split_attempts_table() -> None:
    assert CONFIG.system_id == "bizdev_contacts"
    assert CONFIG.attempts_table == BIZDEV_CONTACTS_ATTEMPTS_TABLE
    assert CONFIG.lease_key == "bizdev_contacts"
    assert CONFIG.env_prefix == "BIZDEV_CONTACTS"


def test_claim_sql_references_bizdev_contacts_attempts() -> None:
    sql = claim_matching_chunk_sql(CONFIG)
    assert BIZDEV_CONTACTS_ATTEMPTS_TABLE in sql
    assert "google_sheets_attempts" not in sql


def test_chunk_drain_module_binds_config() -> None:
    module = build_chunk_drain_module(CONFIG)
    assert module.config is CONFIG
    assert "bizdev_contacts_attempts" in module.claim_matching_chunk_sql()
