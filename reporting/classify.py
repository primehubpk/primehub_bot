"""Classify a parcel status into the daily-report buckets."""
from __future__ import annotations

from typing import Literal

ParcelBucket = Literal["delivered", "in_transit", "exception"]

_EXCEPTION_TOKENS = (
    "exception",
    "delay",
    "delayed",
    "on hold",
    "hold",
    "return",
    "rto",
    "undeliver",
    "fail",
    "cancel",
    "refus",
    "not_found",
    "not found",
    "no record",
    "lost",
    "damaged",
)

_DELIVERED_TOKENS = (
    "delivered",
    "delivery completed",
    "successfully delivered",
)


def classify_status(status: str | None) -> ParcelBucket:
    """Map a free-text M&P status onto one daily-report bucket.

    "Out for delivery" stays in-transit. Anything that looks like a hold,
    return, failure, or missing record is an exception. Everything else
    (booked, picked, reached destination, …) is in-transit.
    """
    text = (status or "").strip().lower()
    if not text:
        return "exception"
    if any(token in text for token in _EXCEPTION_TOKENS):
        return "exception"
    if "out for delivery" in text:
        return "in_transit"
    if any(token in text for token in _DELIVERED_TOKENS) or (
        "deliver" in text and "attempt" not in text
    ):
        return "delivered"
    return "in_transit"
