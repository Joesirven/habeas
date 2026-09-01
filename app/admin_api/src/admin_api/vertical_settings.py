"""Owner vertical settings API — per-vertical notification toggles.

Persists flags on ``data_verticals.settings_json`` (migration
20260827200000). Auth mirrors owner_connectors: vertical-scoped access via
``require_vertical_access`` plus the owner role set; mutations reject the
view-only Data vertical and data_user principals.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from habeas_privacy_core.db.pool import get_pool
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from admin_api.drop_pipeline import _require_database
from admin_api.owner_connectors import (
    OwnerRolePrincipal,
    VerticalAccessPrincipal,
    _reject_owner_mutations,
    _validate_vertical,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/owner", tags=["owner-vertical-settings"])


class VerticalSettingsOut(BaseModel):
    notify_email: bool = False
    notify_slack: bool = False


class VerticalSettingsPatch(BaseModel):
    notify_email: bool | None = None
    notify_slack: bool | None = None


def _settings_out(raw: Any) -> VerticalSettingsOut:
    """asyncpg returns jsonb as str when no codec is registered."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    stored = raw if isinstance(raw, dict) else {}
    return VerticalSettingsOut(
        notify_email=stored.get("notify_email") is True,
        notify_slack=stored.get("notify_slack") is True,
    )


@router.get(
    "/verticals/{vertical_id}/settings",
    response_model=VerticalSettingsOut,
)
async def get_vertical_settings(
    vertical_id: str,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> VerticalSettingsOut:
    """Read notification toggles for an assigned vertical (defaults false/false)."""
    _ = principal
    _validate_vertical(vertical_id)
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        raw = await conn.fetchval(
            """
            SELECT settings_json
              FROM data_verticals
             WHERE id = $1
            """,
            vertical_id,
        )
    if raw is None:
        raise HTTPException(status_code=404, detail="vertical not found")
    return _settings_out(raw)


@router.patch(
    "/verticals/{vertical_id}/settings",
    response_model=VerticalSettingsOut,
)
async def patch_vertical_settings(
    vertical_id: str,
    body: VerticalSettingsPatch,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> VerticalSettingsOut:
    """Merge a partial settings patch into ``data_verticals.settings_json``."""
    _validate_vertical(vertical_id)
    _reject_owner_mutations(vertical_id, principal)
    patch = body.model_dump(exclude_none=True)
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        if patch:
            raw = await conn.fetchval(
                """
                UPDATE data_verticals
                   SET settings_json = COALESCE(settings_json, '{}::jsonb) || $2::jsonb
                 WHERE id = $1
                RETURNING settings_json
                """,
                vertical_id,
                json.dumps(patch),
            )
        else:
            raw = await conn.fetchval(
                """
                SELECT settings_json
                  FROM data_verticals
                 WHERE id = $1
                """,
                vertical_id,
            )
    if raw is None:
        raise HTTPException(status_code=404, detail="vertical not found")
    out = _settings_out(raw)
    if patch:
        logger.info("owner_vertical_settings_patch vertical_id=%s", vertical_id)
    return out
