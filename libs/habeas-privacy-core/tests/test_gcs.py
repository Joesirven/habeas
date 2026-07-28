"""GCS adapter path helpers and in-memory transport."""

from __future__ import annotations

import pytest

from habeas_privacy_core.adapters.gcs import (
    access_artifact_path,
    clear_gcs_store,
    read_object,
    suppression_dwids_path,
    write_object,
)


@pytest.fixture(autouse=True)
def _clear_store():
    clear_gcs_store()
    yield
    clear_gcs_store()


def test_access_artifact_path_layout():
    assert (
        access_artifact_path("proc-1", "req-9", "person.tsv")
        == "bulk-run/proc-1/request/req-9/person.tsv"
    )


def test_suppression_dwids_path_layout():
    assert suppression_dwids_path("proc-1") == "bulk-run/proc-1/suppression/dwids.txt"


@pytest.mark.asyncio
async def test_write_read_round_trip():
    uri = await write_object(
        "fulfillment-bucket",
        suppression_dwids_path("p1"),
        b"111|222",
        content_type="text/plain",
    )
    assert uri == "gs://fulfillment-bucket/bulk-run/p1/suppression/dwids.txt"
    assert await read_object("fulfillment-bucket", "bulk-run/p1/suppression/dwids.txt") == b"111|222"


@pytest.mark.asyncio
async def test_missing_object_raises_file_not_found():
    with pytest.raises(FileNotFoundError, match="gs://fulfillment-bucket/missing"):
        await read_object("fulfillment-bucket", "missing")


def test_signed_url_ttl_clamped_to_v4_limit():
    from habeas_privacy_core.adapters.gcs import signed_url_for_gcs_uri

    # Google rejects V4 signed URLs beyond 7 days; 30-day retention comes from
    # the bucket lifecycle rule, not the URL.
    url = signed_url_for_gcs_uri("gs://b/bulk-run/p/request/r/f.txt", ttl_days=30)
    assert url is not None
    assert "ttl_days=7" in url

    default_url = signed_url_for_gcs_uri("gs://b/bulk-run/p/request/r/f.txt")
    assert default_url is not None
    assert "ttl_days=7" in default_url


@pytest.mark.asyncio
async def test_custom_transport_failure_surfaces_without_body():
    async def boom(_bucket: str, _path: str, _data: bytes | None) -> bytes | None:
        raise RuntimeError("transport down")

    with pytest.raises(RuntimeError, match="transport down"):
        await write_object("b", "p", b"secret-pii", transport=boom)
