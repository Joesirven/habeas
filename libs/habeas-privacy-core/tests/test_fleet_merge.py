"""Unit tests for fleet inventory merge."""

from __future__ import annotations

from habeas_privacy_core.fleet.merge import (
    CloudRunServiceInput,
    SchedulerJobInput,
    merge_fleet_inventory,
)
from habeas_privacy_core.fleet.models import DiscoveryWarning


def _by_key(inventory):
    return {w.worker_key: w for w in inventory.workers}


class TestMergeFleetInventory:
    def test_scheduler_only(self) -> None:
        inv = merge_fleet_inventory(
            env_prefix="dpra-dev",
            discovery_mode="gcp",
            jobs=[
                SchedulerJobInput(name="dpra-dev-matching", schedule="*/5 * * * *"),
            ],
        )
        workers = _by_key(inv)
        assert set(workers) == {"matching"}
        row = workers["matching"]
        assert row.deployed is False
        assert row.scheduled is True
        assert row.base_url is None
        assert row.schedule_job_keys == ["matching"]
        assert "scheduler" in row.sources

    def test_cloud_run_only(self) -> None:
        inv = merge_fleet_inventory(
            env_prefix="dpra-dev",
            discovery_mode="gcp",
            services=[
                CloudRunServiceInput(
                    name="reaper-dev",
                    url="https://reaper-dev-xyz.run.app",
                ),
            ],
        )
        workers = _by_key(inv)
        assert set(workers) == {"reaper"}
        row = workers["reaper"]
        assert row.deployed is True
        assert row.scheduled is False
        assert row.schedule_job_keys == []
        assert row.service_name == "reaper-dev"
        assert row.base_url == "https://reaper-dev-xyz.run.app"
        assert "cloud_run" in row.sources

    def test_both_scheduler_and_run(self) -> None:
        inv = merge_fleet_inventory(
            env_prefix="dpra-dev",
            discovery_mode="gcp",
            jobs=[
                SchedulerJobInput(name="dpra-dev-matching", schedule="*/5 * * * *"),
            ],
            services=[
                CloudRunServiceInput(
                    name="matching-dev",
                    url="https://matching-dev.run.app",
                ),
            ],
        )
        row = _by_key(inv)["matching"]
        assert row.deployed is True
        assert row.scheduled is True
        assert sorted(row.sources) == ["cloud_run", "scheduler"]

    def test_multi_job_worker(self) -> None:
        inv = merge_fleet_inventory(
            env_prefix="dpra-dev",
            discovery_mode="gcp",
            jobs=[
                SchedulerJobInput(name="dpra-dev-drop-ingestor-land"),
                SchedulerJobInput(name="dpra-dev-drop-ingestor-promote"),
            ],
            services=[
                CloudRunServiceInput(name="drop-ingestor-dev", url="https://ing.run.app"),
            ],
            attempt_tables=["drop_ingest_attempts"],
        )
        workers = _by_key(inv)
        assert "drop_ingestor" in workers
        assert "drop_ingestor_land" not in workers
        row = workers["drop_ingestor"]
        assert sorted(row.schedule_job_keys) == [
            "drop_ingestor_land",
            "drop_ingestor_promote",
        ]
        assert row.attempt_table == "drop_ingest_attempts"
        assert row.label == "Drop Ingestor"

    def test_multi_job_collapses_via_env_without_cloud_run(self) -> None:
        """IAM / local fallback: env parent key must collapse land+promote jobs."""
        inv = merge_fleet_inventory(
            env_prefix="dpra-dev",
            discovery_mode="gcp",
            jobs=[
                SchedulerJobInput(name="dpra-dev-drop-ingestor-land"),
                SchedulerJobInput(name="dpra-dev-drop-ingestor-promote"),
            ],
            services=[],
            env_urls={"drop_ingestor": "http://127.0.0.1:8082"},
            attempt_tables=["drop_ingest_attempts"],
        )
        workers = _by_key(inv)
        assert "drop_ingestor" in workers
        assert "drop_ingestor_land" not in workers
        assert "drop_ingestor_promote" not in workers
        row = workers["drop_ingestor"]
        assert sorted(row.schedule_job_keys) == [
            "drop_ingestor_land",
            "drop_ingestor_promote",
        ]
        assert row.base_url == "http://127.0.0.1:8082"
        assert row.deployed is False
        assert row.scheduled is True
        assert "env" in row.sources
        assert "scheduler" in row.sources
        assert row.attempt_table == "drop_ingest_attempts"

    def test_env_url_fill_in(self) -> None:
        inv = merge_fleet_inventory(
            env_prefix="dpra-dev",
            discovery_mode="local",
            jobs=[
                SchedulerJobInput(name="dpra-dev-matching"),
            ],
            env_urls={"matching": "http://127.0.0.1:8081/"},
        )
        row = _by_key(inv)["matching"]
        assert row.base_url == "http://127.0.0.1:8081"
        assert "env" in row.sources
        assert inv.discovery_mode == "local"

    def test_env_url_does_not_override_cloud_run(self) -> None:
        inv = merge_fleet_inventory(
            env_prefix="dpra-dev",
            discovery_mode="gcp",
            services=[
                CloudRunServiceInput(name="matching-dev", url="https://matching.run.app"),
            ],
            env_urls={"matching": "http://localhost:9"},
        )
        assert _by_key(inv)["matching"].base_url == "https://matching.run.app"

    def test_alias_dispatcher_service(self) -> None:
        inv = merge_fleet_inventory(
            env_prefix="dpra-dev",
            discovery_mode="gcp",
            services=[
                CloudRunServiceInput(
                    name="data-fulfillment-dispatcher-dev",
                    url="https://dfd.run.app",
                ),
            ],
            jobs=[
                SchedulerJobInput(name="dpra-dev-data-fulfillment"),
            ],
        )
        workers = _by_key(inv)
        assert "data_fulfillment" in workers
        row = workers["data_fulfillment"]
        assert row.deployed is True
        assert row.scheduled is True
        assert row.schedule_job_keys == ["data_fulfillment"]

    def test_excludes_admin_api(self) -> None:
        inv = merge_fleet_inventory(
            env_prefix="dpra-dev",
            discovery_mode="gcp",
            services=[
                CloudRunServiceInput(name="admin-api-dev", url="https://admin.run.app"),
                CloudRunServiceInput(name="matching-dev", url="https://m.run.app"),
            ],
        )
        assert set(_by_key(inv)) == {"matching"}

    def test_attempt_table_only_worker(self) -> None:
        inv = merge_fleet_inventory(
            env_prefix="dpra-dev",
            discovery_mode="local",
            attempt_tables=["axios_headquarters_attempts", "core_queue_test_attempts"],
        )
        workers = _by_key(inv)
        assert "axios_headquarters" in workers
        assert workers["axios_headquarters"].attempt_table == "axios_headquarters_attempts"
        assert workers["axios_headquarters"].label == "Axios HQ"
        # deny-listed test table must not create a worker
        assert "core_queue_test" not in workers

    def test_discovery_warnings_passthrough(self) -> None:
        warn = DiscoveryWarning(code="cloud_run_list_denied", detail="403")
        inv = merge_fleet_inventory(
            env_prefix="dpra-dev",
            discovery_mode="gcp",
            discovery_warnings=[warn],
        )
        assert inv.discovery_warnings == [warn]
        assert inv.workers == []
