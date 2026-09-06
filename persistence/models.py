"""SQLAlchemy persistence models for the logistics foundation."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class ParcelModel(Base):
    """Persisted parcel/current shipment state."""

    __tablename__ = "parcels"

    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_number: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(100))
    cod_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="PKR")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tracking_events: Mapped[list["TrackingEventModel"]] = relationship(
        back_populates="parcel",
        cascade="all, delete-orphan",
    )
    payments: Mapped[list["PaymentModel"]] = relationship(
        back_populates="parcel",
        cascade="all, delete-orphan",
    )
    shipper_advices: Mapped[list["ShipperAdviceModel"]] = relationship(
        back_populates="parcel",
        cascade="all, delete-orphan",
    )


class TrackingEventModel(Base):
    """Historical parcel status event."""

    __tablename__ = "tracking_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), index=True)
    status: Mapped[str] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(String(255))
    raw_status: Mapped[str | None] = mapped_column(String(255))

    parcel: Mapped[ParcelModel] = relationship(back_populates="tracking_events")


class PaymentModel(Base):
    """COD payment observation."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), index=True)
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    received_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="PKR")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    parcel: Mapped[ParcelModel] = relationship(back_populates="payments")


class ShipperAdviceModel(Base):
    """Submitted or pending shipper advice."""

    __tablename__ = "shipper_advices"

    id: Mapped[int] = mapped_column(primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), index=True)
    advice_text: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    parcel: Mapped[ParcelModel] = relationship(back_populates="shipper_advices")
