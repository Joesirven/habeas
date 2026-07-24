"""Interim suppression: batch DWID list in GCS with in-app ping (KTD-10, R31)."""

from __future__ import annotations

from collections.abc import Sequence

from habeas_privacy_core.adapters.gcs import (
    GcsTransport,
    signed_url_for_gcs_uri,
    suppression_interim_dwids_path,
    write_object,
)
from data_fulfillment_dispatcher.suppression import format_dwid_pipe, merge_dwids, parse_dwid_pipe
from habeas_privacy_core.adapters.gcs import read_object


async def write_interim_suppression_batch(
    *,
    bucket: str,
    process_id: str,
    dwids: Sequence[str],
    transport: GcsTransport | None = None,
) -> tuple[str, str | None]:
    """Write interim pipe-delimited DWID batch; return (gs:// URI, shareable URL)."""
    path = suppression_interim_dwids_path(process_id)
    existing: list[str] = []
    try:
        body = await read_object(bucket, path, transport=transport)
        existing = parse_dwid_pipe(body)
    except FileNotFoundError:
        existing = []
    merged = merge_dwids(existing, dwids)
    gcs_uri = await write_object(
        bucket,
        path,
        format_dwid_pipe(merged),
        content_type="text/plain; charset=utf-8",
        transport=transport,
    )
    return gcs_uri, signed_url_for_gcs_uri(gcs_uri)
