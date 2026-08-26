"""Deprecated helper — Auth0 matching moved to the auth0 worker.

matching-dev drain is DROP-only. Email, phone, and NDZ cycles must not look up
or persist Auth0 vendor ids. This module stays importable so existing tests can
still resolve ``run_auth0_vertical_match``; the function is a no-op.
"""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.models.intake import DropListType

__all__ = ["run_auth0_vertical_match"]


async def run_auth0_vertical_match(
    conn: Any,
    *,
    request_id: str,
    attempt_id: int,
    list_type: DropListType | str | None = None,
    hash_fields: dict[str, Any] | None = None,
    email_hash: str | None = None,
    pipeline: Any | None = None,
    persist: Any | None = None,
) -> dict[str, Any]:
    """No-op. Auth0 matching moved to the auth0 worker.

    Returns immediately without BigQuery lookup or ``request_vertical_matching``
    writes. Signature kept for import compatibility; arguments are unused.
    """
    _ = (
        conn,
        request_id,
        attempt_id,
        list_type,
        hash_fields,
        email_hash,
        pipeline,
        persist,
    )
    return {}
