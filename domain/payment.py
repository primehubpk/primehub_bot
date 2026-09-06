"""Payment domain schema."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Payment(BaseModel):
    """COD payment observation independent of database representation."""

    model_config = ConfigDict(extra="forbid")

    tracking_number: str = Field(min_length=1, max_length=100)
    expected_amount: Decimal = Field(ge=0)
    received_amount: Decimal = Field(ge=0)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    paid_at: datetime | None = None
