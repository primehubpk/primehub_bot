"""Tracking event domain schema."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TrackingEvent(BaseModel):
    """Immutable business event representing a parcel status observation."""

    model_config = ConfigDict(extra="forbid")

    tracking_number: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=100)
    occurred_at: datetime
    location: str | None = Field(default=None, max_length=255)
    raw_status: str | None = Field(default=None, max_length=255)
