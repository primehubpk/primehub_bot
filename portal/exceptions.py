"""Structured portal exceptions."""

class PortalError(Exception):
    """Base portal exception."""

class AuthenticationFailed(PortalError):
    """Authentication could not be completed."""

class SessionExpired(PortalError):
    """Persisted session is no longer authenticated."""

class PortalUnavailable(PortalError):
    """Portal is unreachable or unavailable."""

class SelectorNotFound(PortalError):
    """Required deterministic selector was not found."""


class TerminalActionError(PortalError):
    """Resilient action retries and AI recovery were exhausted."""
