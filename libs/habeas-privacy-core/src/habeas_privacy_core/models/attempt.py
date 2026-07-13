"""Queue attempt row models."""

from enum import StrEnum

from pydantic import BaseModel


class AttemptStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_FLIGHT = "in_flight"
    SUCCESS = "success"
    OUTCOME_ERROR = "outcome_error"
    TIMEOUT = "timeout"


class AttemptRow(BaseModel):
    id: int
    status: AttemptStatus
