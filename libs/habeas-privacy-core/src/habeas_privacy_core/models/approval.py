"""Approval workflow models."""

from pydantic import BaseModel


class ApprovalRequest(BaseModel):
    id: int
    request_id: str
    status: str
