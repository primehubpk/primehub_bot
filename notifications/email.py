"""SMTP/transactional email notification adapter."""
from __future__ import annotations

from email.message import EmailMessage
from typing import Callable

from .service import Notification, NotificationChannel


class EmailNotifier:
    """Email adapter with injected transport for testability."""

    channel = NotificationChannel.EMAIL

    def __init__(
        self,
        transport: Callable[[EmailMessage], object],
        sender: str,
        recipient: str,
    ) -> None:
        self._transport = transport
        self._sender = sender
        self._recipient = recipient

    def send(self, notification: Notification) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = self._recipient
        message["Subject"] = notification.title
        message.set_content(notification.message)
        self._transport(message)
