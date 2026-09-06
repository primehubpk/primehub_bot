"""Small HTTP transport boundary used by provider adapters."""
from __future__ import annotations

from typing import Any

import httpx

from rehan_bot.ai.errors import ProviderError, ProviderErrorKind, classify_status


class JsonTransport:
    """POST JSON with bounded timeouts and normalized provider errors."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = httpx.Timeout(timeout_seconds)

    def post(self, provider: str, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, str(exc), provider) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, str(exc), provider) from exc

        if response.status_code >= 400:
            kind = classify_status(response.status_code)
            raise ProviderError(kind, response.text[:500], provider)

        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(ProviderErrorKind.INVALID_REQUEST, "Provider returned invalid JSON", provider) from exc
