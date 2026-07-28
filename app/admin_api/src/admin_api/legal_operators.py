"""Authorized operators for legal/admin command palette People group."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from admin_api.drop_pipeline import _require_database
from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_LEGAL, ROLE_SUPER_ADMIN
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/legal", tags=["legal-operators"])

LegalOperatorsPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)),
]


class LegalOperator(BaseModel):
    email: str
    kind: str  # assignee | legal_team


@router.get("/operators", response_model=list[LegalOperator])
async def list_legal_operators(_principal: LegalOperatorsPrincipal):
    """Assignees and legal-team members only — no requester directory (KD18)."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        assignee_rows = await conn.fetch(
            """
            SELECT DISTINCT ar.context_jsonb->>'assignee_identity' AS email
              FROM approval_requests ar
             WHERE ar.status = 'pending'
               AND ar.context_jsonb->>'assignee_identity' IS NOT NULL
               AND ar.context_jsonb->>'assignee_identity' != ''
            """
        )
        team_rows = await conn.fetch(
            """
            SELECT email FROM legal_team_members WHERE active = true ORDER BY email
            """
        )
    operators: list[LegalOperator] = []
    seen: set[str] = set()
    for row in assignee_rows:
        email = str(row["email"] or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        operators.append(LegalOperator(email=email, kind="assignee"))
    for row in team_rows:
        email = str(row["email"] or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        operators.append(LegalOperator(email=email, kind="legal_team"))
    return sorted(operators, key=lambda o: o.email)
