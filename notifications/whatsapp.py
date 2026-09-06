"""WhatsApp notification adapters.

Two transports are supported. ``web`` drives our own WhatsApp Web session
through Playwright (no third-party gateway, no per-message cost); ``api``
posts to a configured HTTP gateway such as CallMeBot.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Callable

from .service import Notification, NotificationChannel
from .whatsapp_web import WhatsAppWebConfig, WhatsAppWebSender, safe_print


class WhatsAppNotifier:
    """Provider-neutral WhatsApp transport adapter."""

    channel = NotificationChannel.WHATSAPP

    def __init__(self, transport: Callable[..., object], recipient: str) -> None:
        self._transport = transport
        self._recipient = recipient

    def send(self, notification: Notification) -> None:
        self._transport(
            recipient=self._recipient,
            message=f"[{notification.severity.upper()}] {notification.title}\n{notification.message}",
        )


class WhatsAppWebNotifier:
    """Deliver notifications through our own WhatsApp Web session."""

    channel = NotificationChannel.WHATSAPP

    def __init__(self, sender: WhatsAppWebSender) -> None:
        self._sender = sender

    def send(self, notification: Notification) -> None:
        self._sender.send(
            "\n".join(
                (
                    f"*{notification.title}*",
                    "",
                    notification.message,
                )
            )
        )


logger = logging.getLogger("rehan_bot.notifications.whatsapp")


def _field(source: Any, names: tuple[str, ...]) -> Any:
    """Read the first non-empty field from a mapping or an attribute object."""
    for name in names:
        if isinstance(source, dict):
            value = source.get(name)
        else:
            value = getattr(source, name, None)
        if value is not None and str(value).strip():
            return value
    return None


def _latest_event(events: Any) -> Any:
    """Return the most recent event; history is stored oldest-first."""
    try:
        timed = [
            event
            for event in events
            if isinstance(_field(event, ("occurred_at", "timestamp")), datetime)
        ]
        if timed:
            return max(timed, key=lambda event: _field(event, ("occurred_at", "timestamp")))
    except TypeError:
        pass
    return events[-1]


def format_tracking_message(tracking_data: Any) -> str:
    """Format parcel details: CN, Status, Details/Location, Timestamp."""
    cn = _field(tracking_data, ("tracking_number", "cn", "consignment_number"))
    status = _field(tracking_data, ("status",))
    location = _field(tracking_data, ("location", "details", "current_location"))
    timestamp = _field(tracking_data, ("occurred_at", "timestamp", "delivery_date"))

    # Location/timestamp may live on the newest event rather than the top level.
    events = getattr(tracking_data, "events", None)
    if events is None and isinstance(tracking_data, dict):
        events = tracking_data.get("events")
    if events:
        latest = _latest_event(events)
        if location is None:
            location = _field(latest, ("location", "details"))
        if timestamp is None:
            timestamp = _field(latest, ("occurred_at", "timestamp"))

    if isinstance(timestamp, datetime):
        timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")

    return "\n".join(
        (
            "\U0001F4E6 M&P PARCEL UPDATE",
            "",
            f"CN: {cn or 'N/A'}",
            f"Status: {status or 'N/A'}",
            f"Details/Location: {location or 'N/A'}",
            f"Timestamp: {timestamp or 'N/A'}",
        )
    )


def send_via_gateway(
    phone_number: str,
    message: str,
    api_url: str | None = None,
    callmebot_key: str | None = None,
) -> bool:
    """Dispatch one message through an HTTP WhatsApp gateway."""
    api_url = (
        api_url if api_url is not None else os.environ.get("WHATSAPP_API_URL", "")
    ).strip()
    callmebot_key = (
        callmebot_key
        if callmebot_key is not None
        else os.environ.get("WHATSAPP_CALLMEBOT_APIKEY", "")
    ).strip()

    try:
        if api_url:
            payload = json.dumps(
                {"phone": phone_number, "message": message}
            ).encode("utf-8")
            request = urllib.request.Request(
                api_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
            safe_print(f"[WhatsApp] Dispatched parcel update to {phone_number}")
            logger.info(
                "WhatsApp tracking notification dispatched to %s", phone_number
            )
            return True

        if callmebot_key:
            query = urllib.parse.urlencode(
                {
                    "phone": phone_number,
                    "text": message,
                    "apikey": callmebot_key,
                }
            )
            url = f"https://api.callmebot.com/whatsapp.php?{query}"
            with urllib.request.urlopen(url, timeout=10) as response:
                response.read()
            safe_print(f"[WhatsApp] Dispatched parcel update to {phone_number}")
            logger.info(
                "WhatsApp tracking notification dispatched to %s", phone_number
            )
            return True
    except Exception as exc:
        safe_print(f"[WhatsApp] Dispatch to {phone_number} failed: {exc}")
        logger.warning(
            "WhatsApp dispatch to %s failed: %s", phone_number, exc
        )
        return False

    # No WhatsApp gateway is configured: surface the exact payload that would
    # be dispatched so the run stays observable without failing tracking.
    safe_print(f"[WhatsApp] -> {phone_number}")
    safe_print(message)
    logger.info(
        "WhatsApp gateway not configured; payload logged for %s", phone_number
    )
    return False


def send_tracking_whatsapp(phone_number: str, tracking_data: Any) -> bool:
    """Format the extracted tracking result and dispatch it to WhatsApp.

    The transport is selected by ``WHATSAPP_MODE`` and defaults to our own
    WhatsApp Web session.
    """
    message = format_tracking_message(tracking_data)

    mode = (os.environ.get("WHATSAPP_MODE", "web") or "web").strip().lower()
    if mode == "off":
        logger.info("WhatsApp delivery is disabled (WHATSAPP_MODE=off)")
        return False

    if mode == "api":
        return send_via_gateway(phone_number, message)

    try:
        sender = WhatsAppWebSender(WhatsAppWebConfig.from_env(phone_number))
        return sender.send(message)
    except Exception as exc:
        safe_print(f"[WhatsApp] Web dispatch to {phone_number} failed: {exc}")
        logger.warning("WhatsApp Web dispatch to %s failed: %s", phone_number, exc)
        return False


def whatsapp_mode(settings: Any) -> str:
    """Return the configured transport: ``web``, ``api`` or ``off``."""
    mode = str(getattr(settings, "whatsapp_mode", "web") or "web").strip().lower()
    return mode if mode in {"web", "api", "off"} else "web"


def build_web_sender(settings: Any) -> WhatsAppWebSender | None:
    """Build the Playwright WhatsApp sender when it is configured."""
    if whatsapp_mode(settings) != "web":
        return None

    phone = str(getattr(settings, "whatsapp_phone", "") or "").strip()
    if not phone:
        logger.warning(
            "WHATSAPP_PHONE is empty; WhatsApp Web delivery stays disabled"
        )
        return None

    return WhatsAppWebSender(WhatsAppWebConfig.from_settings(settings))


def build_notifier(settings: Any) -> WhatsAppWebNotifier | None:
    """Build a NotificationService adapter for the configured transport."""
    sender = build_web_sender(settings)
    return WhatsAppWebNotifier(sender) if sender is not None else None


def build_tracking_notifier(settings: Any) -> Callable[[Any], None] | None:
    """Build the per-parcel WhatsApp callback used by the tracking job."""
    mode = whatsapp_mode(settings)
    if mode == "off":
        return None

    phone = str(getattr(settings, "whatsapp_phone", "") or "").strip()
    if not phone:
        logger.warning(
            "WHATSAPP_PHONE is empty; tracking results will not be sent to WhatsApp"
        )
        return None

    if mode == "web":
        sender = build_web_sender(settings)
        if sender is None:
            return None

        def notify_web(result: Any) -> None:
            sender.send(format_tracking_message(result))

        return notify_web

    api_url = str(getattr(settings, "whatsapp_api_url", "") or "").strip()
    callmebot_key = str(getattr(settings, "whatsapp_callmebot_apikey", "") or "").strip()

    def notify_api(result: Any) -> None:
        send_via_gateway(
            phone,
            format_tracking_message(result),
            api_url=api_url,
            callmebot_key=callmebot_key,
        )

    return notify_api
