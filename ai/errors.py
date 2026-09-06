"""AI provider error types and HTTP status classification."""
from __future__ import annotations

from enum import Enum


class ProviderErrorKind(str, Enum):
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    INVALID_REQUEST = "invalid_request"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ProviderError(Exception):
    """A provider failure that is safe for fallback logic."""

    def __init__(self, kind: ProviderErrorKind, message: str, provider: str) -> None:
        self.kind = kind
        self.message = message
        self.provider = provider
        super().__init__(f"{provider}:{kind.value}: {message}")


def classify_status(status_code: int) -> ProviderErrorKind:
    if status_code in (401, 403):
        return ProviderErrorKind.AUTHENTICATION
    if status_code == 429:
        return ProviderErrorKind.RATE_LIMIT
    if 400 <= status_code < 500:
        return ProviderErrorKind.INVALID_REQUEST
    if status_code in (408, 504):
        return ProviderErrorKind.TIMEOUT
    if status_code >= 500:
        return ProviderErrorKind.UNAVAILABLE
    return ProviderErrorKind.UNKNOWN
