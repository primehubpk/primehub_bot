"""Daily reporting service backed by persistence."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rehan_bot.notifications.service import Notification, NotificationService
from rehan_bot.persistence.models import ParcelModel, PaymentModel, ShipperAdviceModel

from .classify import classify_status
from .summary import DailySummary, aggregate_statuses

logger = logging.getLogger("rehan_bot.reporting")


class DailyReportService:
    """Build and dispatch the current logistics summary."""

    def __init__(
        self,
        session: Session,
        notifications: NotificationService,
        whatsapp_sender: Any | None = None,
    ) -> None:
        self._session = session
        self._notifications = notifications
        self._whatsapp_sender = whatsapp_sender

    def build(self) -> DailySummary:
        parcels = self._session.scalars(select(ParcelModel)).all()
        statuses = [parcel.status for parcel in parcels]
        total, delivered, in_transit, exceptions = aggregate_statuses(statuses)
        returns = sum(
            1
            for parcel in parcels
            if "return" in (parcel.status or "").strip().lower()
        )
        advice_rows = self._session.scalars(
            select(ShipperAdviceModel).where(ShipperAdviceModel.submitted_at.is_(None))
        ).all()
        payments = self._session.scalars(select(PaymentModel)).all()
        expected = sum(
            (Decimal(str(x.expected_amount)) for x in payments), Decimal("0.00")
        )
        received = sum(
            (Decimal(str(x.received_amount)) for x in payments), Decimal("0.00")
        )
        return DailySummary(
            delivered=delivered,
            in_transit=in_transit,
            returns=returns,
            pending_shipper_advice=len(advice_rows),
            expected_cod=expected,
            received_cod=received,
            total_checked=total,
            exceptions=exceptions,
        )

    def dispatch(self, summary: DailySummary | None = None) -> DailySummary:
        result = summary or self.build()
        self._notifications.send(
            Notification(
                event="DAILY_LOGISTICS_SUMMARY",
                title="Daily Logistics Summary",
                message=result.to_whatsapp(),
                severity="info",
            )
        )
        return result

    def send_whatsapp(self, summary: DailySummary | None = None) -> bool:
        """Send the emoji daily report through WhatsApp Web and wait for ack.

        Returns True only when the transport confirmed delivery. The report
        is still dispatched to other notification channels when WhatsApp is
        not configured, so a scheduled run never silently drops the summary.
        """
        result = summary or self.build()
        if self._whatsapp_sender is None:
            self.dispatch(result)
            logger.info(
                "Daily report dispatched without a WhatsApp Web sender "
                "(total=%s delivered=%s in_transit=%s exceptions=%s)",
                result.total,
                result.delivered,
                result.in_transit,
                result.exception_count,
            )
            return False

        try:
            sent = bool(self._whatsapp_sender.send(result.to_whatsapp()))
        except Exception as exc:
            logger.warning("Daily WhatsApp report failed: %s", exc, exc_info=exc)
            return False

        if sent:
            logger.info(
                "Daily WhatsApp report confirmed sent "
                "(total=%s delivered=%s in_transit=%s exceptions=%s)",
                result.total,
                result.delivered,
                result.in_transit,
                result.exception_count,
            )
        else:
            logger.warning("Daily WhatsApp report was not acknowledged")
        return sent

    def close(self) -> None:
        self._session.close()


# Keep classify_status importable from the service module for older tests.
__all__ = ["DailyReportService", "classify_status"]
