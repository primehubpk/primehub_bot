"""Standalone COD reconciliation job."""
from __future__ import annotations

from rehan_bot.automation.payments import CodTransaction
from rehan_bot.persistence.repositories.payment_repo import (
    PaymentRepository,
    ReconciliationResult,
)


class ReconciliationJob:
    """Coordinate normalized payment transactions with persistence."""

    def __init__(self, repository: PaymentRepository) -> None:
        self._repository = repository

    def run(
        self,
        transactions: tuple[CodTransaction, ...],
    ) -> tuple[ReconciliationResult, ...]:
        """Persist every transaction and return reconciliation results."""
        return tuple(self._repository.record(transaction) for transaction in transactions)
