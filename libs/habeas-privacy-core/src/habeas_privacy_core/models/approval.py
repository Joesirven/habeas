"""Approval workflow models."""

from pydantic import BaseModel

__all__ = ["ApprovalRequest"]


class ApprovalRequest(BaseModel):
    id: int
    request_id: str
    action_type: str
    status: str
    approver_role: str | None = None
