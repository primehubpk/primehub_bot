"""Component health probes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class HealthResult:
    """Result of a component health probe."""

    component: str
    healthy: bool
    detail: str = ""


class HealthChecker:
    """Run small independent health probes."""

    def __init__(self, probes: dict[str, Callable[[], bool]]) -> None:
        self._probes = probes

    def check(self) -> tuple[HealthResult, ...]:
        """Run all probes without allowing one failure to stop the rest."""
        results: list[HealthResult] = []
        for name, probe in self._probes.items():
            try:
                healthy = bool(probe())
                results.append(HealthResult(name, healthy))
            except Exception as exc:
                results.append(HealthResult(name, False, str(exc)))
        return tuple(results)
