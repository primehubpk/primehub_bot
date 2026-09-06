"""COD statement extraction, portal download, and normalization."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from playwright.sync_api import Page

from rehan_bot.automation.actions import ActionType, RecoveryProtocol, ResilientActions
from rehan_bot.portal.exceptions import TerminalActionError
from rehan_bot.portal.selectors import PortalSelectors


@dataclass(frozen=True)
class CodTransaction:
    """Normalized COD transaction row."""

    tracking_number: str
    expected_amount: Decimal
    received_amount: Decimal
    currency: str = "PKR"


class PaymentStatementParser:
    """Parse CSV statements without knowing persistence details."""

    REQUIRED_COLUMNS = {
        "tracking_number",
        "expected_amount",
        "received_amount",
    }

    def parse_csv(self, content: str) -> tuple[CodTransaction, ...]:
        """Parse and validate a CSV payment statement."""
        reader = csv.DictReader(io.StringIO(content))
        fieldnames = {name.strip().lower().replace(" ", "_") for name in (reader.fieldnames or [])}
        # Rebuild reader with normalized headers
        raw = csv.DictReader(io.StringIO(content))
        if raw.fieldnames:
            raw.fieldnames = [name.strip().lower().replace(" ", "_") for name in raw.fieldnames]
        missing = self.REQUIRED_COLUMNS - fieldnames
        if missing:
            # Accept common M&P aliases before failing
            alias_map = {
                "cn": "tracking_number",
                "consignment": "tracking_number",
                "consignment_no": "tracking_number",
                "cod": "expected_amount",
                "cod_amount": "expected_amount",
                "amount": "received_amount",
                "paid": "received_amount",
            }
            if raw.fieldnames:
                raw.fieldnames = [alias_map.get(name, name) for name in raw.fieldnames]
                fieldnames = set(raw.fieldnames)
            missing = self.REQUIRED_COLUMNS - fieldnames
            if missing:
                raise ValueError(f"Missing required payment columns: {sorted(missing)}")

        rows: list[CodTransaction] = []
        for line_number, row in enumerate(raw, start=2):
            try:
                tracking = (row.get("tracking_number") or "").strip()
                if not tracking:
                    raise ValueError("tracking_number is empty")
                expected = Decimal((row.get("expected_amount") or "").strip() or "0")
                received = Decimal((row.get("received_amount") or "").strip() or "0")
                currency = (row.get("currency") or "PKR").strip().upper()
                if expected < 0 or received < 0:
                    raise ValueError("amounts cannot be negative")
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"Invalid payment row at line {line_number}: {exc}") from exc
            rows.append(CodTransaction(tracking, expected, received, currency))
        return tuple(rows)


class MPortalPaymentPage:
    """Fetch COD statements from the live M&P payments screen."""

    def __init__(
        self,
        page: Page,
        payments_url: str,
        recovery: RecoveryProtocol | None = None,
        action_timeout_ms: int = 3500,
        recovery_max_retries: int = 3,
    ) -> None:
        if not payments_url.strip():
            raise ValueError("MP_PAYMENTS_URL is required")
        self._page = page
        self._payments_url = payments_url.strip()
        self._actions = ResilientActions(
            page,
            recovery=recovery,
            timeout_ms=action_timeout_ms,
            max_retries=recovery_max_retries,
        )
        self._parser = PaymentStatementParser()

    def fetch_transactions(self) -> tuple[CodTransaction, ...]:
        """Download a statement file, otherwise scrape the on-screen table."""
        self._actions.execute(
            ActionType.NAVIGATE,
            value=self._payments_url,
            target_description="open payments URL",
        )
        downloaded = self._try_download()
        if downloaded:
            return self._parser.parse_csv(downloaded)
        return self._scrape_table()

    def _try_download(self) -> str:
        try:
            with self._page.expect_download(timeout=12_000) as pending:
                self._actions.execute(
                    ActionType.CLICK,
                    PortalSelectors.PAYMENTS_DOWNLOAD,
                    target_description="download payment statement",
                )
            download = pending.value
            path = download.path()
            if path is None:
                return ""
            return Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _scrape_table(self) -> tuple[CodTransaction, ...]:
        rows = self._page.locator(PortalSelectors.PAYMENTS_TABLE_ROWS.candidates[0])
        transactions: list[CodTransaction] = []
        try:
            count = rows.count()
        except Exception as exc:
            raise TerminalActionError("Payment statement table is not available") from exc

        for index in range(count):
            cells = rows.nth(index).locator("td")
            try:
                texts = [cell.inner_text().strip() for cell in cells.all()]
            except Exception:
                continue
            if len(texts) < 2:
                continue
            tracking = texts[0]
            amounts = [item.replace(",", "") for item in texts[1:] if _looks_numeric(item)]
            if not tracking or not amounts:
                continue
            expected = Decimal(amounts[0])
            received = Decimal(amounts[1] if len(amounts) > 1 else amounts[0])
            transactions.append(CodTransaction(tracking, expected, received))
        return tuple(transactions)


def _looks_numeric(value: str) -> bool:
    cleaned = value.replace(",", "").replace("PKR", "").strip()
    try:
        Decimal(cleaned)
        return True
    except (InvalidOperation, ValueError):
        return False
