"""Deterministic M&P tracking workflow with safe recovery hooks."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from collections.abc import Callable, Sequence
from typing import Protocol

from playwright.sync_api import Page

from rehan_bot.automation.actions import ActionType, RecoveryProtocol, ResilientActions
from rehan_bot.portal.exceptions import PortalUnavailable
from rehan_bot.portal.selectors import PortalSelectors

logger = logging.getLogger("rehan_bot.automation.tracking")

LABEL_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "delivery_date",
        (
            "delivery date",
            "delivered on",
            "delivered at",
            "delivery time",
            "delivery date/time",
            "date of delivery",
        ),
    ),
    (
        "location",
        (
            "current location",
            "last location",
            "location",
            "current city",
            "destination city",
            "destination",
            "station",
            "branch",
            "city",
        ),
    ),
    (
        "status",
        (
            "current status",
            "shipment status",
            "parcel status",
            "delivery status",
            "status",
        ),
    ),
    (
        "cod_amount",
        (
            "cod amount",
            "cod",
        ),
    ),
    (
        "event_date",
        (
            "date & time",
            "date and time",
            "date/time",
            "date time",
            "event date",
            "activity date",
            "booking date",
            "date",
            "time",
        ),
    ),
)

DATE_TIME_PATTERN = re.compile(
    r"\d{1,4}[-/ ][A-Za-z0-9]{1,9}[-/ ]\d{2,4}"
    r"(?:[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp]\.?[Mm]\.?)?)?"
)

DATE_FORMATS: tuple[str, ...] = (
    # M&P renders slash dates as MM/DD/YYYY (observed: 08/22/2026 22:37:55),
    # so month-first is attempted before day-first.
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %I:%M %p",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y %I:%M %p",
    "%d-%m-%Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y %H:%M",
    "%d-%b-%Y %I:%M %p",
    "%d-%b-%Y",
    "%d %b %Y %H:%M",
    "%d %b %Y",
    "%d %B %Y %H:%M",
    "%d %B %Y",
    "%d/%m/%y %H:%M",
    "%d/%m/%y",
)

NON_VALUE_TOKENS = frozenset({"", "-", "--", "n/a", "na", "null", "none", "."})


def clean_text(text: object) -> str:
    """Collapse whitespace into a single-line string."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def classify_label(label: str) -> str | None:
    """Map a portal field label onto a known result field."""
    normalized = clean_text(label).strip(" :*#").lower()
    if not normalized:
        return None
    for field, aliases in LABEL_ALIASES:
        if any(normalized == alias for alias in aliases):
            return field
    for field, aliases in LABEL_ALIASES:
        if any(alias in normalized for alias in aliases):
            return field
    return None


def is_value_present(value: str) -> bool:
    """Whether a scraped cell carries real content."""
    return clean_text(value).lower() not in NON_VALUE_TOKENS


def looks_like_location(text: str) -> bool:
    """Distinguish a station/city cell from an event description cell."""
    cleaned = clean_text(text)
    if not is_value_present(cleaned):
        return False
    if len(cleaned) > 40 or cleaned.endswith("."):
        return False
    return len(cleaned.split()) <= 4


def looks_like_status(text: str) -> bool:
    """Whether a timeline cell reads like a status label rather than prose."""
    cleaned = clean_text(text)
    if not is_value_present(cleaned):
        return False
    return len(cleaned) <= 60 and len(cleaned.split()) <= 8


def parse_label_value_pairs(lines: Sequence[str]) -> dict[str, str]:
    """Extract known fields from ``Label: Value`` style text lines."""
    fields: dict[str, str] = {}
    for raw_line in lines:
        line = clean_text(raw_line)
        if not line or ":" not in line:
            continue
        label, _, value = line.partition(":")
        field = classify_label(label)
        if field is None or field in fields:
            continue
        if is_value_present(value):
            fields[field] = clean_text(value)
    return fields


def parse_datetime_text(text: str) -> datetime | None:
    """Parse the portal's date/time text using its known formats."""
    cleaned = clean_text(text)
    if not cleaned:
        return None

    match = DATE_TIME_PATTERN.search(cleaned)
    candidates = [match.group(0)] if match else []
    candidates.append(cleaned)

    for candidate in candidates:
        normalized = candidate.replace(".", "").strip()
        for date_format in DATE_FORMATS:
            try:
                return datetime.strptime(normalized, date_format)
            except ValueError:
                continue
    return None


def parse_amount(text: str) -> Decimal | None:
    """Parse a COD amount such as ``Rs. 2,500.00``."""
    cleaned = clean_text(text)
    if not cleaned:
        return None
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", cleaned)
    if match is None:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class TrackingEventData:
    """Normalized tracking event returned by the portal."""

    tracking_number: str
    status: str
    occurred_at: datetime
    location: str | None = None
    raw_status: str | None = None


@dataclass(frozen=True)
class TrackingResult:
    """Normalized tracking response."""

    tracking_number: str
    status: str
    events: tuple[TrackingEventData, ...]
    delivery_date: datetime | None = None
    cod_amount: Decimal | None = None


class TrackingPage(Protocol):
    """Capability contract consumed by TrackingJob."""

    def search(self, tracking_number: str) -> None:
        """Search a tracking number."""

    def read_result(self, tracking_number: str) -> TrackingResult:
        """Read the currently displayed result."""


class MPortalTrackingPage:
    """Deterministic M&P tracking adapter with resilient actions."""

    def __init__(
        self,
        page: Page,
        tracking_url: str | None,
        recovery: RecoveryProtocol | None = None,
        relogin: Callable[[], object] | None = None,
        action_timeout_ms: int = 1500,
        recovery_max_retries: int = 3,
        loader_timeout_ms: int = 45_000,
        result_timeout_ms: int = 45_000,
    ) -> None:
        self._page = page
        self._tracking_url = (tracking_url or "").strip()
        self._relogin = relogin
        self._loader_timeout_ms = loader_timeout_ms
        self._result_timeout_ms = result_timeout_ms
        self._actions = ResilientActions(
            page,
            recovery=recovery,
            timeout_ms=action_timeout_ms,
            max_retries=recovery_max_retries,
        )
        self._opened = False

    def open(self) -> None:
        """Reach the tracking screen via direct URL or guarded sidebar navigation."""
        if self._tracking_url:
            current = ""
            try:
                current = self._page.url
            except Exception:
                current = ""
            if "complaintreport" in current.lower():
                current = ""
            if self._tracking_url.rstrip("/") not in current.rstrip("/"):
                self._actions.execute(
                    ActionType.NAVIGATE,
                    value=self._tracking_url,
                    target_description="open tracking URL",
                    verify=lambda page: self._tracking_url.rstrip("/") in page.url.rstrip("/")
                    or "/login" in page.url.lower(),
                )
                # The portal may redirect a stale browser session to login
                # after it accepted the original credentials. Reauthenticate
                # in the same live page, then resume this exact operation.
                if "/login" in self._page.url.lower():
                    if self._relogin is None:
                        raise RuntimeError("Portal session expired and no re-login callback is configured")
                    self._relogin()
                    self._actions.execute(
                        ActionType.NAVIGATE,
                        value=self._tracking_url,
                        target_description="resume tracking after session re-login",
                        verify=lambda page: self._tracking_url.rstrip("/") in page.url.rstrip("/"),
                    )
            self._opened = True
            return

        self._actions.execute(
            ActionType.CLICK,
            PortalSelectors.NAV_TRACKING_PARENT,
            target_description="expand Tracking sidebar menu",
            child_selector=PortalSelectors.NAV_TRACKING_CHILD.candidates[0],
        )
        self._opened = True

    def search(self, tracking_number: str) -> None:
        """Search one M&P consignment number with multi-step AI fallback."""
        number = tracking_number.strip()
        if not number:
            raise ValueError("Tracking number cannot be empty.")

        if not self._opened:
            self.open()

        self._actions.execute(
            ActionType.FILL,
            PortalSelectors.TRACKING_INPUT,
            value=number,
            target_description="fill tracking number",
            verify=lambda page: self._input_contains(page, number),
        )
        self._actions.execute(
            ActionType.CLICK,
            PortalSelectors.TRACKING_SUBMIT,
            target_description="submit tracking search",
            verify=lambda page: self._search_accepted(page),
        )
        self._settle_after_search()

    def search_bulk(self, tracking_numbers: tuple[str, ...]) -> None:
        """Fill a multi-CN field when the portal accepts bulk input."""
        numbers = tuple(item.strip() for item in tracking_numbers if item.strip())
        if len(numbers) <= 1:
            if numbers:
                self.search(numbers[0])
            return
        if not self._opened:
            self.open()
        payload = "\n".join(numbers)
        self._actions.execute(
            ActionType.FILL,
            PortalSelectors.TRACKING_INPUT,
            value=payload,
            target_description="fill bulk tracking numbers",
        )
        self._actions.execute(
            ActionType.CLICK,
            PortalSelectors.TRACKING_SUBMIT,
            target_description="submit bulk tracking search",
        )

    def read_result(self, tracking_number: str) -> TrackingResult:
        """Read the normalized tracking result rendered by the AJAX response."""
        self._settle_after_search()

        if self._not_found_visible():
            return self._not_found_result(tracking_number)

        fields = self._extract_fields()
        timeline = self._extract_timeline_rows()

        if timeline:
            return self._result_from_timeline(tracking_number, timeline, fields)

        return self._result_from_fields(tracking_number, fields)

    def _result_from_timeline(
        self,
        tracking_number: str,
        timeline: list[tuple[datetime, str, str | None]],
        fields: dict[str, str],
    ) -> TrackingResult:
        """Build the result from the portal's event timeline (newest wins)."""
        ordered = sorted(timeline, key=lambda row: row[0])
        latest_at, latest_status, latest_location = ordered[-1]

        events = tuple(
            TrackingEventData(
                tracking_number=tracking_number,
                status=status,
                occurred_at=occurred_at,
                location=location,
                raw_status=status,
            )
            for occurred_at, status, location in ordered
        )

        delivery_date = (
            latest_at if "deliver" in latest_status.lower() else None
        ) or parse_datetime_text(fields.get("delivery_date", ""))

        logger.info(
            "Tracking %s -> status=%s location=%s at=%s (%d events)",
            tracking_number,
            latest_status,
            latest_location,
            latest_at,
            len(events),
        )

        return TrackingResult(
            tracking_number=tracking_number,
            status=latest_status,
            events=events,
            delivery_date=delivery_date,
            cod_amount=parse_amount(fields.get("cod_amount", "")),
        )

    def _result_from_fields(
        self, tracking_number: str, fields: dict[str, str]
    ) -> TrackingResult:
        """Build the result from labelled detail fields when no timeline exists."""
        status = self._normalize_status_text(fields.get("status", ""))
        if not status:
            status = self._normalize_status_text(self._read_status_text())

        if not status:
            page_text = self._read_status_page() or ""
            if self._looks_like_not_found(page_text):
                return self._not_found_result(tracking_number)
            raise ValueError("M&P tracking status was empty or could not be read.")

        if self._looks_like_not_found(status):
            return self._not_found_result(tracking_number)

        if not looks_like_status(status):
            # Whole-page text is not a status. Storing it would poison the
            # parcel record and the WhatsApp alert.
            raise ValueError(
                "M&P tracking status could not be isolated from the page "
                f"(read {len(status)} characters instead of a status label)."
            )

        location = fields.get("location") or None
        delivery_date = parse_datetime_text(fields.get("delivery_date", ""))
        event_date = parse_datetime_text(fields.get("event_date", "")) or delivery_date

        if delivery_date is None and event_date is not None and "deliver" in status.lower():
            delivery_date = event_date

        logger.info(
            "Tracking %s -> status=%s location=%s delivery_date=%s",
            tracking_number,
            status,
            location,
            delivery_date,
        )

        event = TrackingEventData(
            tracking_number=tracking_number,
            status=status,
            occurred_at=event_date or datetime.now(),
            location=location,
            raw_status=status,
        )
        return TrackingResult(
            tracking_number=tracking_number,
            status=status,
            events=(event,),
            delivery_date=delivery_date,
            cod_amount=parse_amount(fields.get("cod_amount", "")),
        )

    def _extract_timeline_rows(self) -> list[tuple[datetime, str, str | None]]:
        """Read timeline events, preferring the React timeline over tables."""
        return self._extract_div_timeline() or self._extract_table_timeline()

    def _extract_div_timeline(self) -> list[tuple[datetime, str, str | None]]:
        """Read ``.timeline-item`` blocks rendered by the tracking_2 screen."""
        rows: list[tuple[datetime, str, str | None]] = []
        items = self._locate_first_populated(PortalSelectors.TRACKING_TIMELINE_ITEM)
        if items is None:
            return rows

        try:
            item_count = min(items.count(), 60)
        except Exception:
            return rows

        for index in range(item_count):
            item = items.nth(index)

            occurred_at = parse_datetime_text(
                self._inner_text(item, PortalSelectors.TRACKING_TIMELINE_TIMESTAMP)
            )
            if occurred_at is None:
                continue

            status = self._inner_text(item, PortalSelectors.TRACKING_TIMELINE_STATUS)
            if not looks_like_status(status):
                continue

            location = self._inner_text(item, PortalSelectors.TRACKING_TIMELINE_LOCATION)
            rows.append(
                (occurred_at, status, location if looks_like_location(location) else None)
            )

        return rows

    def _locate_first_populated(self, selector_set: object) -> object | None:
        for selector in getattr(selector_set, "candidates", ()):
            try:
                locator = self._page.locator(selector)
                if locator.count():
                    return locator
            except Exception:
                continue
        return None

    @staticmethod
    def _inner_text(scope: object, selector_set: object) -> str:
        for selector in getattr(selector_set, "candidates", ()):
            try:
                locator = scope.locator(selector).first
                if not locator.count():
                    continue
                return clean_text(locator.inner_text(timeout=1_000))
            except Exception:
                continue
        return ""

    def _extract_table_timeline(self) -> list[tuple[datetime, str, str | None]]:
        """Read the ``date | status | location | description`` table rows."""
        rows: list[tuple[datetime, str, str | None]] = []
        try:
            tables = self._page.locator("table")
            table_count = min(tables.count(), 6)
        except Exception:
            return rows

        for table_index in range(table_count):
            table = tables.nth(table_index)
            try:
                table_rows = table.locator("tr")
                row_count = min(table_rows.count(), 60)
            except Exception:
                continue

            for row_index in range(row_count):
                try:
                    cells = [
                        clean_text(text)
                        for text in table_rows.nth(row_index).locator("td").all_inner_texts()
                    ]
                except Exception:
                    continue
                if len(cells) < 2:
                    continue

                occurred_at = parse_datetime_text(cells[0])
                if occurred_at is None or not looks_like_status(cells[1]):
                    continue

                location = None
                for cell in cells[2:]:
                    if looks_like_location(cell):
                        location = cell
                        break

                rows.append((occurred_at, cells[1], location))

        return rows

    @staticmethod
    def _not_found_result(tracking_number: str) -> TrackingResult:
        event = TrackingEventData(
            tracking_number=tracking_number,
            status="NOT_FOUND",
            occurred_at=datetime.now(),
            raw_status="NOT_FOUND",
        )
        return TrackingResult(
            tracking_number=tracking_number,
            status="NOT_FOUND",
            events=(event,),
        )

    # =====================================================================
    # AJAX SETTLING
    # =====================================================================

    def _settle_after_search(self) -> None:
        """Let the 'Please Wait' overlay finish, then require a rendered answer."""
        self._wait_for_loader_to_clear()
        self._wait_for_result_or_not_found()

    def _wait_for_loader_to_clear(self) -> None:
        """Wait until every visible loader overlay reports state='hidden'."""
        visible = self._visible_loaders()
        if not visible:
            return

        logger.info("Waiting for M&P loader overlay to clear: %s", ", ".join(visible))
        deadline = time.monotonic() + self._loader_timeout_ms / 1000

        for selector in visible:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            try:
                self._page.wait_for_selector(
                    selector, state="hidden", timeout=remaining_ms
                )
            except Exception:
                if self._answer_present():
                    logger.info(
                        "Loader %s still reported visible but the result is rendered",
                        selector,
                    )
                    return
                raise PortalUnavailable(
                    "M&P 'Please Wait' overlay did not clear within "
                    f"{self._loader_timeout_ms}ms (selector {selector})"
                )

    def _visible_loaders(self, appear_timeout_ms: int = 3_000) -> list[str]:
        """Collect loader selectors that are actually on screen right now.

        The overlay is injected a moment after the click, so a short appearance
        window avoids racing past it.
        """
        deadline = time.monotonic() + appear_timeout_ms / 1000
        while True:
            found = [
                selector
                for selector in PortalSelectors.LOADER_OVERLAY.candidates
                if self._selector_visible(selector)
            ]
            if found or time.monotonic() >= deadline or self._answer_present():
                return found
            try:
                self._page.wait_for_timeout(200)
            except Exception:
                return found

    def _wait_for_result_or_not_found(self) -> None:
        """Require either a visible result container or a 'no record' marker."""
        deadline = time.monotonic() + self._result_timeout_ms / 1000
        while time.monotonic() < deadline:
            if self._answer_present():
                return
            try:
                self._page.wait_for_timeout(250)
            except Exception:
                break

        raise PortalUnavailable(
            "M&P tracking result never rendered within "
            f"{self._result_timeout_ms}ms after the search"
        )

    def _answer_present(self) -> bool:
        return self._result_rendered() or self._not_found_visible()

    def _result_rendered(self) -> bool:
        """Whether extractable result content is on screen.

        Container selectors alone are not enough: the React shell renders empty
        result scaffolding before the AJAX answer arrives.
        """
        if self._timeline_visible():
            return True
        if self._extract_timeline_rows():
            return True
        if self._extract_detail_fields():
            return True
        return bool(self._extract_from_tables())

    def _timeline_visible(self) -> bool:
        return any(
            self._selector_visible(selector)
            for selector in (
                *PortalSelectors.TRACKING_TIMELINE_ITEM.candidates,
                *PortalSelectors.TRACKING_TIMELINE_TIMESTAMP.candidates,
            )
        )

    def _not_found_visible(self) -> bool:
        if any(
            self._selector_visible(selector)
            for selector in PortalSelectors.TRACKING_NOT_FOUND.candidates
        ):
            return True
        if self._timeline_visible():
            return False
        return self._looks_like_not_found(self._read_status_page())

    def _selector_visible(self, selector: str, timeout_ms: int = 250) -> bool:
        try:
            locator = self._page.locator(selector).first
            return bool(locator.count()) and locator.is_visible(timeout=timeout_ms)
        except Exception:
            return False

    def _search_accepted(self, page: Page) -> bool:
        """Confirm the click actually triggered the AJAX search."""
        del page
        if self._visible_loaders(appear_timeout_ms=1_500):
            return True
        return self._answer_present() or self._status_visible(self._page)

    # =====================================================================
    # FIELD EXTRACTION
    # =====================================================================

    def _extract_fields(self) -> dict[str, str]:
        """Read status/location/date from the rendered result."""
        fields = self._extract_detail_fields()

        for field, value in self._extract_from_tables().items():
            fields.setdefault(field, value)

        if len(fields) < 3:
            page_text = ""
            try:
                page_text = self._page.locator("body").inner_text(timeout=2_000)
            except Exception:
                page_text = ""
            for field, value in parse_label_value_pairs(page_text.splitlines()).items():
                fields.setdefault(field, value)

        return fields

    def _extract_detail_fields(self) -> dict[str, str]:
        """Read the readonly ``label`` + ``input`` shipment detail pairs."""
        fields: dict[str, str] = {}
        labels = self._locate_first_populated(PortalSelectors.TRACKING_DETAIL_LABEL)
        if labels is None:
            return fields

        try:
            label_count = min(labels.count(), 40)
        except Exception:
            return fields

        for index in range(label_count):
            label = labels.nth(index)
            try:
                field = classify_label(label.inner_text(timeout=500))
            except Exception:
                continue
            if field is None or field in fields:
                continue

            try:
                control = label.locator("xpath=..").locator("input, textarea").first
                if not control.count():
                    continue
                value = clean_text(control.input_value(timeout=500))
            except Exception:
                continue

            if is_value_present(value):
                fields[field] = value

        return fields

    def _extract_from_tables(self) -> dict[str, str]:
        """Map table headers (or label cells) onto result fields."""
        fields: dict[str, str] = {}
        try:
            tables = self._page.locator("table")
            table_count = min(tables.count(), 6)
        except Exception:
            return fields

        for index in range(table_count):
            table = tables.nth(index)
            try:
                if not table.is_visible(timeout=250):
                    continue
            except Exception:
                continue

            for field, value in self._read_horizontal_table(table).items():
                fields.setdefault(field, value)
            for field, value in self._read_vertical_table(table).items():
                fields.setdefault(field, value)

        return fields

    def _read_horizontal_table(self, table: object) -> dict[str, str]:
        """Read a header-row table where the first body row holds the values."""
        fields: dict[str, str] = {}
        try:
            headers = [clean_text(text) for text in table.locator("th").all_inner_texts()]
            rows = table.locator("tbody tr")
            if not headers or not rows.count():
                return fields
            cells = [clean_text(text) for text in rows.first.locator("td").all_inner_texts()]
        except Exception:
            return fields

        for header, cell in zip(headers, cells):
            field = classify_label(header)
            if field is None or field in fields:
                continue
            if is_value_present(cell):
                fields[field] = cell
        return fields

    def _read_vertical_table(self, table: object) -> dict[str, str]:
        """Read a two-column ``Label | Value`` table."""
        fields: dict[str, str] = {}
        try:
            rows = table.locator("tr")
            row_count = min(rows.count(), 40)
        except Exception:
            return fields

        for index in range(row_count):
            try:
                cells = [
                    clean_text(text)
                    for text in rows.nth(index).locator("td, th").all_inner_texts()
                ]
            except Exception:
                continue
            if len(cells) != 2:
                continue
            field = classify_label(cells[0])
            if field is None or field in fields:
                continue
            if is_value_present(cells[1]):
                fields[field] = cells[1]
        return fields

    def _read_status_text(self) -> str:
        selectors = (
            "table td",
            ".badge",
            ".status-text",
            ".tracking-status",
            ".shipment-status",
            "[class*='status' i]",
            "[data-testid*='status' i]",
            "table tbody tr td",
            "td",
        )
        candidates: list[str] = []
        for selector in selectors:
            try:
                locator = self._page.locator(selector)
                for raw_text in locator.all_inner_texts():
                    cleaned = self._clean_text(raw_text)
                    if not cleaned:
                        continue
                    if cleaned.lower() in {"status", "tracking number", "consignment number", "current location", "latest event", "timestamp", "date"}:
                        continue
                    if self._looks_like_not_found(cleaned):
                        return "NOT_FOUND"
                    if self._looks_like_status(cleaned):
                        candidates.append(cleaned)
            except Exception:
                continue
        if candidates:
            return candidates[0]
        page_text = self._read_status_page()
        if self._looks_like_not_found(page_text):
            return "NOT_FOUND"
        return page_text

    def _read_status_page(self) -> str:
        try:
            page_text = self._page.locator("body").inner_text(timeout=1_000)
        except Exception:
            return ""
        cleaned = self._clean_text(page_text)
        if self._looks_like_not_found(cleaned):
            return "NOT_FOUND"
        return cleaned

    @staticmethod
    def _looks_like_not_found(text: str) -> bool:
        lower = MPortalTrackingPage._clean_text(text).lower()
        if not lower:
            return False
        for phrase in (
            "no record found",
            "no result found",
            "tracking number not found",
            "consignment not found",
            "invalid cn",
            "invalid tracking number",
            "record not found",
            "not found",
        ):
            if phrase in lower:
                return True
        return False

    @staticmethod
    def _looks_like_status(text: str) -> bool:
        lower = MPortalTrackingPage._clean_text(text).lower()
        if not lower:
            return False
        if MPortalTrackingPage._looks_like_not_found(lower):
            return False
        strong_tokens = (
            "delivered",
            "in transit",
            "transit",
            "pending",
            "processing",
            "out for delivery",
            "picked up",
            "returned",
            "cancelled",
            "canceled",
            "hold",
            "on hold",
            "exception",
            "arrived",
            "received",
            "inbound",
            "shipment",
            "status",
        )
        return any(token in lower for token in strong_tokens)

    @staticmethod
    def _normalize_status_text(text: str) -> str:
        cleaned = MPortalTrackingPage._clean_text(text)
        if not cleaned:
            return ""
        if MPortalTrackingPage._looks_like_not_found(cleaned):
            return "NOT_FOUND"
        if "|" in cleaned:
            cleaned = cleaned.split("|")[-1].strip()
        if "\n" in cleaned:
            cleaned = " ".join(part.strip() for part in cleaned.splitlines() if part.strip())
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" :-|[]()")
        return cleaned

    @staticmethod
    def _clean_text(text: str) -> str:
        return clean_text(text)


    @staticmethod
    def _input_contains(page: Page, value: str) -> bool:
        for selector in PortalSelectors.TRACKING_INPUT.candidates:
            try:
                if page.locator(selector).first.input_value(timeout=300).strip() == value:
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _status_visible(page: Page) -> bool:
        try:
            page.wait_for_timeout(400)
        except Exception:
            pass
        for selector in PortalSelectors.TRACKING_STATUS.candidates:
            try:
                locator = page.locator(selector).first
                if locator.count() and locator.is_visible():
                    return True
            except Exception:
                continue
        return False
