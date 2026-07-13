"""Privacy request domain models."""

from enum import StrEnum

from pydantic import BaseModel, Field


class IntakeSource(StrEnum):
    WEBFORM = "webform"
    DROP = "drop"
    CSV_BATCH = "csv_batch"


class RequestSummary(BaseModel):
    """Minimal request shape for list/detail views."""

    id: str
    intake_source: IntakeSource
    requestor_state: str = Field(min_length=2, max_length=2)
