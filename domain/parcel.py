"""Parcel domain schema."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Parcel(BaseModel):
    """Courier parcel represented independently of persistence."""

    model_config = ConfigDict(extra="forbid")

    tracking_number: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=100)
    cod_amount: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    last_synced_at: datetime | None = None
