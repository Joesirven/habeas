"""Queue attempt row models."""

from pydantic import BaseModel

from habeas_privacy_core.queue.status import AttemptStatus

__all__ = ["AttemptStatus", "AttemptRow"]


class AttemptRow(BaseModel):
    id: int
    status: AttemptStatus
