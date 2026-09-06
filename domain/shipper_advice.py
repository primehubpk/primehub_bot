"""Shipper Advice domain schema."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ShipperAdvice(BaseModel):
    """Validated shipper advice request."""

    model_config = ConfigDict(extra="forbid")

    tracking_number: str = Field(min_length=1, max_length=100)
    advice_text: str = Field(min_length=1, max_length=5_000)
    submitted_at: datetime | None = None
    submitted: bool = False
