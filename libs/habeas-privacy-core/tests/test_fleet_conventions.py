"""Unit tests for fleet naming conventions."""

from __future__ import annotations

from habeas_privacy_core.fleet.conventions import (
    ATTEMPT_TABLE_DENYLIST,
    CONTROL_PLANE_SERVICE_EXCLUDES,
    SERVICE_ALIAS_TO_WORKER_KEY,
    attempt_table_for_worker,
    is_denied_attempt_table,
    is_excluded_service_slug,
    job_key_from_job_name,
    job_name_from_job_key,
    label_from_worker_key,
    parse_worker_fleet_urls,
    resolve_worker_key_for_job,
    service_slug_from_name,
    service_suffix_from_prefix,
    worker_key_from_attempt_table,
    worker_key_from_service_slug,
)


class TestPrefixAndJobNames:
    def test_service_suffix_from_dev_prefix(self) -> None:
        assert service_suffix_from_prefix("dpra-dev") == "-dev"

    def test_service_suffix_from_prod_prefix(self) -> None:
        assert service_suffix_from_prefix("dpra-prod") == ""

    def test_job_key_round_trip(self) -> None:
        prefix = "dpra-dev"
        job_key = "drop_connector_download"
        name = job_name_from_job_key(job_key, prefix)
        assert name == "dpra-dev-drop-connector-download"
        assert job_key_from_job_name(name, prefix) == job_key

    def test_job_key_from_full_resource_name(self) -> None:
        full = (
            "projects/example-gcp-project/locations/us-east4/jobs/"
            "dpra-dev-drop-ingestor-land"
        )
        assert job_key_from_job_name(full, "dpra-dev") == "drop_ingestor_land"

    def test_job_key_rejects_wrong_prefix(self) -> None:
        assert job_key_from_job_name("dpra-prod-matching", "dpra-dev") is None


class TestServiceAliasesAndExcludes:
    def test_exclude_admin_api(self) -> None:
        assert "admin-api" in CONTROL_PLANE_SERVICE_EXCLUDES
        assert is_excluded_service_slug("admin-api")
        assert worker_key_from_service_slug("admin-api") is None

    def test_exclude_drain_services(self) -> None:
        assert is_excluded_service_slug("matching-drain")
        assert worker_key_from_service_slug("matching-drain-worker") is None

    def test_data_fulfillment_alias(self) -> None:
        assert (
            SERVICE_ALIAS_TO_WORKER_KEY["data-fulfillment-dispatcher"]
            == "data_fulfillment"
        )
        assert (
            worker_key_from_service_slug("data-fulfillment-dispatcher")
            == "data_fulfillment"
        )

    def test_data_vertical_matching_alias(self) -> None:
        assert SERVICE_ALIAS_TO_WORKER_KEY["data-vertical-matching"] == "matching"
        assert worker_key_from_service_slug("data-vertical-matching") == "matching"
        assert (
            service_slug_from_name("data-vertical-matching-dev", "-dev")
            == "data-vertical-matching"
        )
        assert service_slug_from_name("matching-dev", "-dev") == "matching"
        assert worker_key_from_service_slug("matching") == "matching"

    def test_default_hyphen_to_underscore(self) -> None:
        assert worker_key_from_service_slug("hash-index-refresh") == "hash_index_refresh"

    def test_strip_dev_suffix(self) -> None:
        assert service_slug_from_name("matching-dev", "-dev") == "matching"
        assert service_slug_from_name("matching", "") == "matching"


class TestAttemptTables:
    def test_drop_ingest_exception(self) -> None:
        assert attempt_table_for_worker("drop_ingestor") == "drop_ingest_attempts"
        assert worker_key_from_attempt_table("drop_ingest_attempts") == "drop_ingestor"

    def test_default_attempts_suffix(self) -> None:
        assert attempt_table_for_worker("matching") == "matching_attempts"
        assert worker_key_from_attempt_table("matching_attempts") == "matching"

    def test_deny_test_tables(self) -> None:
        assert "core_queue_test_attempts" in ATTEMPT_TABLE_DENYLIST
        assert is_denied_attempt_table("core_queue_test_attempts")
        assert worker_key_from_attempt_table("core_queue_test_attempts") is None


class TestResolveWorkerKeyForJob:
    def test_multi_job_matches_service(self) -> None:
        known = {"drop_ingestor", "matching"}
        assert (
            resolve_worker_key_for_job("drop_ingestor_land", known) == "drop_ingestor"
        )
        assert (
            resolve_worker_key_for_job("drop_ingestor_promote", known) == "drop_ingestor"
        )

    def test_scheduler_only_keeps_job_key(self) -> None:
        assert resolve_worker_key_for_job("drop_ingestor_land", set()) == (
            "drop_ingestor_land"
        )

    def test_exact_match(self) -> None:
        assert resolve_worker_key_for_job("matching", {"matching"}) == "matching"


class TestLabelsAndEnvUrls:
    def test_label_humanizes(self) -> None:
        assert label_from_worker_key("drop_ingestor") == "Drop Ingestor"
        assert label_from_worker_key("matching") == "Matching"

    def test_label_uses_connection_system(self) -> None:
        assert label_from_worker_key("mailchimp") == "Mailchimp"

    def test_parse_worker_fleet_urls(self) -> None:
        raw = '{"matching": "http://localhost:8081/", "reaper": "http://localhost:8082"}'
        assert parse_worker_fleet_urls(raw) == {
            "matching": "http://localhost:8081",
            "reaper": "http://localhost:8082",
        }

    def test_parse_worker_fleet_urls_invalid(self) -> None:
        assert parse_worker_fleet_urls(None) == {}
        assert parse_worker_fleet_urls("not-json") == {}
        assert parse_worker_fleet_urls("[]") == {}
