"""Suppression artifact: pipe-delimited DWID file under bulk-run prefix.

MVP rebuild strategy: read-merge-write the existing GCS object with the
current request's DWIDs (deduped). First write starts the set when the
object is absent. DWIDs are never written to audit_payload or logs.
"""

from __future__ import annotations

from collections.abc import Sequence

from habeas_privacy_core.adapters.gcs import (
    GcsTransport,
    read_object,
    suppression_dwids_path,
    write_object,
)


def format_dwid_pipe(dwids: Sequence[str]) -> bytes:
    """MVP body: dwid1|dwid2|… (no header)."""
    cleaned = [d.strip() for d in dwids if d and str(d).strip()]
    return "|".join(cleaned).encode("utf-8")


def parse_dwid_pipe(body: bytes) -> list[str]:
    """Parse a pipe-delimited DWID body into ordered unique strings."""
    if not body:
        return []
    text = body.decode("utf-8")
    seen: set[str] = set()
    out: list[str] = []
    for part in text.split("|"):
        dwid = part.strip()
        if not dwid or dwid in seen:
            continue
        seen.add(dwid)
        out.append(dwid)
    return out


def merge_dwids(*groups: Sequence[str]) -> list[str]:
    """Stable dedupe across groups (first-seen order)."""
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for raw in group:
            dwid = str(raw).strip()
            if not dwid or dwid in seen:
                continue
            seen.add(dwid)
            out.append(dwid)
    return out


async def write_suppression_dwids(
    *,
    bucket: str,
    process_id: str,
    dwids: Sequence[str],
    transport: GcsTransport | None = None,
) -> str:
    """Read-merge-write the bulk-run suppression object; return gs:// URI.

    Merges ``dwids`` into any existing ``dwids.txt`` for ``process_id`` so
    prior successful suppressions for the same bulk run are preserved.
    If the object does not exist yet, the current request starts the set.
    """
    path = suppression_dwids_path(process_id)
    existing: list[str] = []
    try:
        body = await read_object(bucket, path, transport=transport)
        existing = parse_dwid_pipe(body)
    except FileNotFoundError:
        # First write for this bulk process starts the suppression set.
        existing = []

    merged = merge_dwids(existing, dwids)
    return await write_object(
        bucket,
        path,
        format_dwid_pipe(merged),
        content_type="text/plain; charset=utf-8",
        transport=transport,
    )
