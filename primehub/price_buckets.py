"""Auto-tag PrimeHub price-bucket checkboxes from the selling price."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveBucket:
    """One row from GET /api/v1/store/metadata priceBuckets."""

    id: str
    label: str
    max_price: int | None = None


def wanted_bucket_labels(price: int, wholesale: bool = False) -> list[str]:
    """Labels the admin checkboxes would tick for this price / pack type."""
    labels: list[str] = []
    if price == 99:
        labels.append("99")
    if price < 299:
        labels.append("Under 299")
    if price < 999:
        labels.append("Under 999")
    if wholesale:
        labels.append("Wholesale deal")
    return labels


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().replace("-", " ").split())


def resolve_bucket_ids(
    price: int,
    live_buckets: list[LiveBucket] | tuple[LiveBucket, ...],
    *,
    wholesale: bool = False,
) -> list[str]:
    """Return live bucket IDs whose labels match the auto-tag rules."""
    wanted = wanted_bucket_labels(price, wholesale=wholesale)
    if not wanted or not live_buckets:
        return []

    ids: list[str] = []
    seen: set[str] = set()
    for label in wanted:
        needle = _normalize(label)
        match = _best_bucket(needle, live_buckets)
        if match is not None and match.id not in seen:
            ids.append(match.id)
            seen.add(match.id)
    return ids


def _best_bucket(needle: str, live_buckets: list[LiveBucket] | tuple[LiveBucket, ...]) -> LiveBucket | None:
    exact = [bucket for bucket in live_buckets if _normalize(bucket.label) == needle]
    if exact:
        return exact[0]
    if needle.isdigit():
        for bucket in live_buckets:
            tokens = _normalize(bucket.label).replace("rs.", " ").split()
            if needle in tokens:
                return bucket
        return None
    for bucket in live_buckets:
        haystack = _normalize(bucket.label)
        if needle in haystack or haystack in needle:
            return bucket
    return None
