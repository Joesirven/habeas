"""Interim access: Vertica script copy-paste + provisioned GCS upload (KTD-11, KD14)."""

from __future__ import annotations

from habeas_privacy_core.adapters.gcs import interim_access_prefix, write_object

VERTICA_SCRIPT_TEMPLATE = """-- Interim access reproduction (copy-paste into Vertica)
-- Request: {request_id}
-- Pre-filled DWIDs: {dwid_list}

SELECT *
  FROM privacy.access_export_sample
 WHERE dwid IN ({dwid_in_clause});

-- Export flat files (operators expect two files) and upload via data-owner screen.
"""


def render_vertica_script(*, request_id: str, dwids: list[str]) -> str:
    cleaned = [d.strip() for d in dwids if d and str(d).strip()]
    dwid_list = ", ".join(cleaned) if cleaned else "(none)"
    in_clause = ", ".join(f"'{d}'" for d in cleaned) if cleaned else "NULL"
    return VERTICA_SCRIPT_TEMPLATE.format(
        request_id=request_id,
        dwid_list=dwid_list,
        dwid_in_clause=in_clause,
    )


async def provision_interim_prefix(
    *,
    bucket: str,
    process_id: str,
    request_id: str,
    transport=None,
) -> str:
    """Provision per-request interim prefix with a README marker object."""
    prefix = interim_access_prefix(process_id, request_id)
    marker_path = f"{prefix}.provisioned"
    return await write_object(
        bucket,
        marker_path,
        b"interim access upload location",
        content_type="text/plain",
        transport=transport,
    )
