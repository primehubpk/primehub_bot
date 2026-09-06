"""Parcel and tracking-event persistence."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from rehan_bot.automation.tracking import TrackingEventData, TrackingResult
from rehan_bot.persistence.models import ParcelModel, TrackingEventModel


class ParcelRepository:
    """Persistence boundary for parcel state and event history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_tracking(self, result: TrackingResult) -> ParcelModel:
        """Idempotently update current parcel state."""
        parcel = self._session.scalar(
            select(ParcelModel).where(
                ParcelModel.tracking_number == result.tracking_number
            )
        )
        if parcel is None:
            parcel = ParcelModel(
                tracking_number=result.tracking_number,
                status=result.status,
                cod_amount=result.cod_amount or Decimal("0"),
            )
            parcel.last_synced_at = result.events[-1].occurred_at if result.events else None
            self._session.add(parcel)
            self._session.flush()
        else:
            parcel.status = result.status
            if result.cod_amount is not None:
                parcel.cod_amount = result.cod_amount
            parcel.last_synced_at = result.events[-1].occurred_at if result.events else None
        return parcel

    def append_event(self, parcel: ParcelModel, event: TrackingEventData) -> TrackingEventModel:
        """Append an event only when the same event is not already present."""
        existing = self._session.scalar(
            select(TrackingEventModel).where(
                TrackingEventModel.parcel_id == parcel.id,
                TrackingEventModel.status == event.status,
                TrackingEventModel.occurred_at == event.occurred_at,
            )
        )
        if existing is not None:
            return existing

        record = TrackingEventModel(
            parcel_id=parcel.id,
            status=event.status,
            occurred_at=event.occurred_at,
            location=event.location,
            raw_status=event.raw_status,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def save_result(self, result: TrackingResult) -> ParcelModel:
        """Persist current state and all new timeline events in one transaction."""
        parcel = self.upsert_tracking(result)
        for event in result.events:
            self.append_event(parcel, event)
        self._session.commit()
        return parcel
