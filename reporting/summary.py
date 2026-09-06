"""Daily logistics summary domain objects."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .classify import classify_status


@dataclass(frozen=True)
class DailySummary:
    """Normalized daily logistics KPI snapshot."""

    delivered: int
    in_transit: int
    returns: int
    pending_shipper_advice: int
    expected_cod: Decimal
    received_cod: Decimal
    total_checked: int | None = None
    exceptions: int | None = None

    @property
    def total(self) -> int:
        if self.total_checked is not None:
            return self.total_checked
        return self.delivered + self.in_transit + self.returns

    @property
    def exception_count(self) -> int:
        if self.exceptions is not None:
            return self.exceptions
        return self.returns

    @property
    def cod_difference(self) -> Decimal:
        return self.received_cod - self.expected_cod

    def to_dict(self) -> dict[str, object]:
        return {
            "total_checked": self.total,
            "delivered": self.delivered,
            "in_transit": self.in_transit,
            "returns": self.returns,
            "exceptions": self.exception_count,
            "pending_shipper_advice": self.pending_shipper_advice,
            "expected_cod": str(self.expected_cod),
            "received_cod": str(self.received_cod),
            "cod_difference": str(self.cod_difference),
        }

    def to_text(self) -> str:
        return (
            "Daily Logistics Summary\n"
            f"Total checked: {self.total}\n"
            f"Delivered: {self.delivered}\n"
            f"In Transit: {self.in_transit}\n"
            f"Delayed / Exceptions: {self.exception_count}\n"
            f"Returns: {self.returns}\n"
            f"Pending Shipper Advice: {self.pending_shipper_advice}\n"
            f"Expected COD: PKR {self.expected_cod:.2f}\n"
            f"Received COD: PKR {self.received_cod:.2f}\n"
            f"COD Difference: PKR {self.cod_difference:.2f}"
        )

    def to_whatsapp(self, when: datetime | None = None) -> str:
        """Emoji-formatted daily report ready to paste into WhatsApp."""
        stamp = when or datetime.now()
        lines = [
            "\U0001F4CA M&P DAILY REPORT",
            f"\U0001F4C5 {stamp.strftime('%A, %d %b %Y')}",
            "",
            f"\U0001F4E6 Total checked: {self.total}",
            f"\u2705 Delivered: {self.delivered}",
            f"\U0001F69A In-Transit: {self.in_transit}",
            f"\u26A0\uFE0F Delayed / Exceptions: {self.exception_count}",
        ]
        if self.pending_shipper_advice:
            lines.append(
                f"\u2757 Pending shipper advice: {self.pending_shipper_advice}"
            )
        if self.expected_cod or self.received_cod:
            lines.extend(
                (
                    "",
                    f"\U0001F4B0 Expected COD: PKR {self.expected_cod:.2f}",
                    f"\U0001F4B5 Received COD: PKR {self.received_cod:.2f}",
                    f"\U0001F4B8 Difference: PKR {self.cod_difference:.2f}",
                )
            )
        return "\n".join(lines)


def aggregate_statuses(statuses: list[str]) -> tuple[int, int, int, int]:
    """Return (total, delivered, in_transit, exceptions) for a status list."""
    delivered = in_transit = exceptions = 0
    for status in statuses:
        bucket = classify_status(status)
        if bucket == "delivered":
            delivered += 1
        elif bucket == "exception":
            exceptions += 1
        else:
            in_transit += 1
    return delivered + in_transit + exceptions, delivered, in_transit, exceptions
