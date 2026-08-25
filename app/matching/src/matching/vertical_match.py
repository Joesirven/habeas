"""Post-DROP Auth0 vertical matching — mart lookup + snapshot persist.

Runs in the same matching-dev cycle as DROP. Failures never fail the DROP
attempt: persist nothing, return allowlisted audit keys only.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.db.vertical_matching import (
    AUTH0_VERTICAL,
    upsert_vertical_matching_snapshot,
)
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.vertical_hash.bq_lookup import (
    DEFAULT_BQ_DATASET as AUTH0_DEFAULT_BQ_DATASET,
)

from matching.adapters.auth0_hash import Auth0HashLookupError, Auth0HashPipeline
from matching.adapters.drop_hash import primary_hash_for_list_type

logger = logging.getLogger(__name__)

__all__ = ["run_auth0_vertical_match"]


def _is_email_list_type(list_type: DropListType | str | None) -> bool:
    if list_type is None:
        return False
    if list_type == DropListType.EMAIL:
        return True
    return str(list_type) == DropListType.EMAIL.value


def auth0_bq_dataset() -> str:
    return (
        os.environ.get("EXTERNAL_HASH_BQ_DATASET", AUTH0_DEFAULT_BQ_DATASET).strip()
        or AUTH0_DEFAULT_BQ_DATASET
    )


def _email_hash(
    *,
    email_hash: str | None,
    hash_fields: dict[str, Any] | None,
) -> str | None:
    if email_hash is not None and str(email_hash).strip():
        return str(email_hash).strip()
    if not hash_fields:
        return None
    value, _via = primary_hash_for_list_type(DropListType.EMAIL, hash_fields)
    return value


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, ValueError) and "plaintext" in str(exc).lower():
        return "auth0_invalid_hash"
    return "auth0_lookup_error"


def _failure_audit(exc: BaseException) -> dict[str, Any]:
    code = _error_code(exc)
    logger.error(
        "auth0_vertical_match_failed",
        extra={
            "event": "auth0_vertical_match_failed",
            "error_code": code,
            "error_summary": redact_error_text(str(exc)),
        },
    )
    return {
        "auth0_bq_dataset": auth0_bq_dataset(),
        "auth0_error_code": code,
    }


async def run_auth0_vertical_match(
    conn: Any,
    *,
    request_id: str,
    attempt_id: int,
    list_type: DropListType | str | None = None,
    hash_fields: dict[str, Any] | None = None,
    email_hash: str | None = None,
    pipeline: Auth0HashPipeline | None = None,
    persist: Any | None = None,
) -> dict[str, Any]:
    """Look up Auth0 vendor ids after a successful DROP email match.

    On success, upserts ``request_vertical_matching`` (0/1/N hits).
    ``Auth0HashLookupError`` and S02 plaintext-``@`` ``ValueError`` persist
    nothing and never raise — DROP success stays intact.
    """
    if not _is_email_list_type(list_type):
        return {}

    hash_value = _email_hash(email_hash=email_hash, hash_fields=hash_fields)
    if not hash_value:
        return {}

    try:
        pipe = pipeline or Auth0HashPipeline()
        result = pipe.match_from_email_hash(hash_value)
        vendor_ids = list(result.consumer_ids or [])
        match_count = int(result.match_count)
        upsert = persist or upsert_vertical_matching_snapshot
        await upsert(
            conn,
            request_id=request_id,
            vertical=AUTH0_VERTICAL,
            match_count=match_count,
            vendor_record_ids=vendor_ids,
            source_matching_attempt_id=attempt_id,
        )
        logger.info(
            "auth0_vertical_match_recorded",
            extra={
                "event": "auth0_vertical_match_recorded",
                "match_count": match_count,
            },
        )
        return {
            "auth0_match_count": match_count,
            "auth0_bq_dataset": auth0_bq_dataset(),
        }
    except (Auth0HashLookupError, ValueError) as exc:
        return _failure_audit(exc)
    except Exception as exc:
        return _failure_audit(exc)
