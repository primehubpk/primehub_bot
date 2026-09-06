"""Telegram notification adapter."""
from __future__ import annotations

from typing import Callable

from .service import Notification, NotificationChannel


class TelegramNotifier:
    """Small Telegram transport adapter."""

    channel = NotificationChannel.TELEGRAM

    def __init__(self, transport: Callable[..., object], chat_id: str) -> None:
        self._transport = transport
        self._chat_id = chat_id

    def send(self, notification: Notification) -> None:
        self._transport(
            chat_id=self._chat_id,
            text=f"[{notification.severity.upper()}] {notification.title}\n{notification.message}",
        )
