"""Simple interval limiter for portal requests."""
from __future__ import annotations

import time


class RateLimiter:
    """Ensure a minimum delay between successive portal operations."""

    def __init__(self, min_interval_seconds: float = 1.5) -> None:
        self._min_interval = max(0.0, min_interval_seconds)
        self._last = 0.0

    def wait(self) -> None:
        """Block until the configured interval has elapsed."""
        if self._min_interval <= 0:
            self._last = time.monotonic()
            return
        now = time.monotonic()
        remaining = self._min_interval - (now - self._last)
        if remaining > 0:
            time.sleep(remaining)
        self._last = time.monotonic()
