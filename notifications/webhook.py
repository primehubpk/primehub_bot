"""Generic webhook notification adapter."""
from __future__ import annotations

from typing import Callable

from .service import Notification, NotificationChannel


class WebhookNotifier:
    """HTTP webhook adapter with injected transport."""

    channel = NotificationChannel.WEBHOOK

    def __init__(self, transport: Callable[..., object], url: str) -> None:
        self._transport = transport
        self._url = url

    def send(self, notification: Notification) -> None:
        self._transport(
            url=self._url,
            json={
                "event": notification.event,
                "title": notification.title,
                "message": notification.message,
                "severity": notification.severity,
            },
        )
