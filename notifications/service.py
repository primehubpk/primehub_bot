"""Decoupled notification dispatcher."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class NotificationChannel(str, Enum):
    """Supported notification channels."""

    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    WEBHOOK = "webhook"


@dataclass(frozen=True)
class Notification:
    """Channel-independent notification payload."""

    event: str
    title: str
    message: str
    severity: str = "warning"


class Notifier(Protocol):
    """Common adapter contract."""

    channel: NotificationChannel

    def send(self, notification: Notification) -> None:
        """Send one notification."""


class NotificationService:
    """Dispatch notifications to configured adapters."""

    def __init__(self, notifiers: tuple[Notifier, ...] = ()) -> None:
        self._notifiers = notifiers

    def send(self, notification: Notification) -> None:
        """Send through every configured notifier."""
        for notifier in self._notifiers:
            notifier.send(notification)
