"""Standalone tracking synchronization job."""
from __future__ import annotations

import logging
from typing import Any, Callable

from rehan_bot.automation.rate_limit import RateLimiter
from rehan_bot.automation.tracking import TrackingPage
from rehan_bot.persistence.repositories.parcel_repo import ParcelRepository

logger = logging.getLogger("rehan_bot.jobs.tracking")


class TrackingJob:
    """Coordinate tracking retrieval with persistence."""

    def __init__(
        self,
        portal: TrackingPage,
        repository: ParcelRepository,
        min_interval_seconds: float = 1.5,
        notifier: Callable[[Any], None] | None = None,
    ) -> None:
        self._portal = portal
        self._repository = repository
        self._limiter = RateLimiter(min_interval_seconds)
        self._notifier = notifier

    def run(self, tracking_numbers: tuple[str, ...]) -> int:
        """Synchronize tracking numbers with retry and rate-limiting."""
        numbers = tuple(item.strip() for item in tracking_numbers if item.strip())
        completed = 0
        last_error: Exception | None = None

        bulk = getattr(self._portal, "search_bulk", None)
        if bulk is not None and len(numbers) > 1:
            try:
                bulk(numbers)
            except Exception:
                pass

        for index, tracking_number in enumerate(numbers):
            if index:
                self._limiter.wait()
            for _attempt in range(2):
                try:
                    self._portal.search(tracking_number)
                    result = self._portal.read_result(tracking_number)
                    self._repository.save_result(result)
                    completed += 1
                    self._notify(result)
                    break
                except Exception as exc:
                    last_error = exc
                    self._limiter.wait()

        if completed == 0 and last_error is not None:
            raise last_error
        return completed

    def _notify(self, result: Any) -> None:
        """Deliver one result without letting delivery break persistence."""
        if self._notifier is None:
            return
        try:
            self._notifier(result)
        except Exception as exc:
            logger.warning(
                "Tracking notification failed for %s: %s",
                getattr(result, "tracking_number", "?"),
                exc,
                exc_info=exc,
            )
