"""Upload-mode CSV connection tests for vertical-scoped connectors."""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.connections.catalog import UPLOAD_SYSTEMS

from admin_api.upload_templates import test_upload_csv

# Re-export for connection_testers / tests.
__all__ = ["UPLOAD_SYSTEMS", "test_upload_system"]


async def test_upload_system(
    system: str,
    *,
    content: bytes,
    multi_pii_delimiter: str | None,
    column_mapping: dict[str, str] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Run the upload CSV test for *system*."""
    if system not in UPLOAD_SYSTEMS:
        return False, "unknown_system", {}
    return await test_upload_csv(
        system=system,
        content=content,
        multi_pii_delimiter=multi_pii_delimiter,
        column_mapping=column_mapping,
    )


# Not a pytest test — called by connection_testers dispatcher.
test_upload_system.__test__ = False
