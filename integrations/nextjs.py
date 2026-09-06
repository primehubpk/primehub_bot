"""Decoupled Next.js courier integration client."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rehan_bot.automation.payments import CodTransaction
from rehan_bot.automation.tracking import TrackingEventData

class NextJsIntegrationError(RuntimeError):
    """Raised when a Next.js courier API request fails."""

@dataclass(frozen=True)
class NextJsClientConfig:
    base_url: str
    service_token: str
    timeout_seconds: float = 15.0

class NextJsCourierClient:
    """Publish normalized logistics data to Next.js APIs."""
    def __init__(self, config: NextJsClientConfig, transport: Callable[..., object] | None = None) -> None:
        self._config = config
        self._transport = transport

    @staticmethod
    def tracking_event_payload(event: TrackingEventData) -> dict[str, object]:
        return {"trackingNumber": event.tracking_number, "status": event.status, "occurredAt": event.occurred_at.isoformat(), "location": event.location, "rawStatus": event.raw_status}

    @staticmethod
    def cod_payload(transaction: CodTransaction) -> dict[str, object]:
        return {"trackingNumber": transaction.tracking_number, "expectedAmount": str(transaction.expected_amount), "receivedAmount": str(transaction.received_amount), "currency": transaction.currency, "difference": str(transaction.received_amount - transaction.expected_amount)}

    def publish_tracking_event(self, event: TrackingEventData) -> None:
        self._post('/api/courier/events', self.tracking_event_payload(event))

    def publish_cod_reconciliation(self, transaction: CodTransaction) -> None:
        self._post('/api/courier/sync', self.cod_payload(transaction))

    def _post(self, path: str, payload: dict[str, object]) -> None:
        url = f"{self._config.base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self._config.service_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        }
        body = json.dumps(payload, separators=(",", ":")).encode('utf-8')
        if self._transport is not None:
            try:
                self._transport(method='POST', url=url, headers=headers, body=body, payload=payload)
                return
            except Exception as exc:
                raise NextJsIntegrationError(str(exc)) from exc
        request = Request(url, data=body, headers=headers, method='POST')
        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as response:
                if not 200 <= response.status < 300:
                    raise NextJsIntegrationError(f"Next.js API returned HTTP {response.status}")
        except HTTPError as exc:
            raise NextJsIntegrationError(f"Next.js API returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise NextJsIntegrationError(f"Next.js API unavailable: {exc}") from exc
