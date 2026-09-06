"""Ordered multimodal fallback chain."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rehan_bot.ai.errors import ProviderError, ProviderErrorKind
from rehan_bot.ai.schemas import VisualSolution
from rehan_bot.ai.vision import VisionImage


class VisionProvider(Protocol):
    def propose(self, image: VisionImage, prompt: str) -> VisualSolution: ...


@dataclass(frozen=True)
class ProviderEntry:
    name: str
    provider: VisionProvider


class VisionFallbackChain:
    """Try providers in order; each provider independently rotates its keys."""

    def __init__(self, providers: tuple[ProviderEntry, ...]) -> None:
        if not providers:
            raise ValueError("At least one vision provider is required")
        self._providers = providers

    @property
    def provider_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self._providers)

    def propose(self, image: VisionImage, prompt: str) -> VisualSolution:
        failures: list[str] = []
        for entry in self._providers:
            try:
                return entry.provider.propose(image, prompt)
            except ProviderError as exc:
                failures.append(f"{entry.name}:{exc.kind.value}: {exc}")
            except Exception as exc:
                failures.append(f"{entry.name}: {exc}")
        raise ProviderError(ProviderErrorKind.UNAVAILABLE, " | ".join(failures), "fallback-chain")
