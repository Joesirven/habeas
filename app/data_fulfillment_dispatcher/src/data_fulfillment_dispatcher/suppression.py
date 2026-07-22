"""Suppression artifact: pipe-delimited DWID file under bulk-run prefix."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from habeas_privacy_core.adapters.gcs import (
    GcsTransport,
    suppression_dwids_path,
    write_object,
)

DwidResolver = Callable[[], Awaitable[list[str]]]


def format_dwid_pipe(dwids: Sequence[str]) -> bytes:
    """MVP body: dwid1|dwid2|… (no header)."""
    cleaned = [d.strip() for d in dwids if d and str(d).strip()]
    return "|".join(cleaned).encode("utf-8")


async def write_suppression_dwids(
    *,
    bucket: str,
    process_id: str,
    dwids: Sequence[str],
    transport: GcsTransport | None = None,
) -> str:
    """Rewrite the bulk-run suppression object; return gs:// URI."""
    path = suppression_dwids_path(process_id)
    return await write_object(
        bucket,
        path,
        format_dwid_pipe(dwids),
        content_type="text/plain; charset=utf-8",
        transport=transport,
    )
