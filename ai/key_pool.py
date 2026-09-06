"""Thread-safe API key rotation with temporary failure quarantine."""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

from rehan_bot.ai.errors import ProviderErrorKind

_QUARANTINE_KINDS = {
    ProviderErrorKind.AUTHENTICATION,
    ProviderErrorKind.RATE_LIMIT,
    ProviderErrorKind.TIMEOUT,
    ProviderErrorKind.UNAVAILABLE,
}


@dataclass
class KeyState:
    key: str
    failures: int = 0
    unavailable_until: float = 0.0


class RoundRobinKeyPool:
    """Rotate keys while temporarily quarantining failing keys."""

    def __init__(self, keys: tuple[str, ...], quarantine_seconds: float = 60.0) -> None:
        cleaned = tuple(key.strip() for key in keys if key and key.strip())
        if not cleaned:
            raise ValueError("API key pool is empty")
        self._states = [KeyState(key) for key in cleaned]
        self._quarantine_seconds = quarantine_seconds
        self._index = 0
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        return len(self._states)

    def next(self) -> KeyState:
        with self._lock:
            now = time.monotonic()
            for _ in self._states:
                state = self._states[self._index]
                self._index = (self._index + 1) % len(self._states)
                if state.unavailable_until <= now:
                    return state
            state = min(self._states, key=lambda item: item.unavailable_until)
            state.unavailable_until = 0.0
            return state

    def round_keys(self) -> tuple[KeyState, ...]:
        """Return each key at most once, preferring keys that are not quarantined."""
        with self._lock:
            now = time.monotonic()
            ready = [state for state in self._states if state.unavailable_until <= now]
            start = self._index % len(self._states)
            self._index = (self._index + 1) % len(self._states)
            ordered: list[KeyState] = []
            source = ready or self._states
            if not ready:
                for state in self._states:
                    state.unavailable_until = 0.0
            for offset in range(len(self._states)):
                state = self._states[(start + offset) % len(self._states)]
                if state in source and state not in ordered:
                    ordered.append(state)
            return tuple(ordered)

    def iter_round(self) -> Iterator[KeyState]:
        yield from self.round_keys()

    def success(self, state: KeyState) -> None:
        with self._lock:
            state.failures = 0
            state.unavailable_until = 0.0

    def failure(self, state: KeyState, kind: ProviderErrorKind) -> None:
        with self._lock:
            state.failures += 1
            if kind in _QUARANTINE_KINDS:
                delay = min(self._quarantine_seconds * (2 ** (state.failures - 1)), 900.0)
                state.unavailable_until = time.monotonic() + delay
