"""Payment and reconciliation persistence."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from rehan_bot.automation.payments import CodTransaction
from rehan_bot.persistence.models import ParcelModel, PaymentModel


@dataclass(frozen=True)
class ReconciliationResult:
    """Business result of expected-versus-received matching."""

    tracking_number: str
    expected_amount: Decimal
    received_amount: Decimal
    difference: Decimal
    matched: bool


def reconcile_amounts(
    expected_amount: Decimal,
    received_amount: Decimal,
    tolerance: Decimal = Decimal("0.00"),
) -> tuple[Decimal, bool]:
    """Calculate discrepancy and whether it is within tolerance."""
    difference = received_amount - expected_amount
    return difference, abs(difference) <= tolerance


class PaymentRepository:
    """Persistence boundary for COD observations and reconciliation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, transaction: CodTransaction) -> ReconciliationResult:
        """Idempotently persist one normalized payment observation."""
        parcel = self._session.scalar(
            select(ParcelModel).where(
                ParcelModel.tracking_number == transaction.tracking_number
            )
        )
        if parcel is None:
            raise ValueError(
                f"No parcel exists for tracking number {transaction.tracking_number}"
            )

        difference, matched = reconcile_amounts(
            transaction.expected_amount,
            transaction.received_amount,
        )

        existing = self._session.scalar(
            select(PaymentModel).where(
                PaymentModel.parcel_id == parcel.id,
                PaymentModel.expected_amount == transaction.expected_amount,
                PaymentModel.received_amount == transaction.received_amount,
                PaymentModel.currency == transaction.currency,
            )
        )
        if existing is None:
            self._session.add(
                PaymentModel(
                    parcel_id=parcel.id,
                    expected_amount=transaction.expected_amount,
                    received_amount=transaction.received_amount,
                    currency=transaction.currency,
                )
            )
            self._session.commit()

        return ReconciliationResult(
            tracking_number=transaction.tracking_number,
            expected_amount=transaction.expected_amount,
            received_amount=transaction.received_amount,
            difference=difference,
            matched=matched,
        )
