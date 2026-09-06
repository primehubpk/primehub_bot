"""Deterministic Shipper Advice workflow."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field
from playwright.sync_api import Page

from rehan_bot.automation.actions import ActionType, RecoveryProtocol, ResilientActions
from rehan_bot.portal.selectors import PortalSelectors


class ShipperAdviceAction(BaseModel):
    """Validated action payload for one shipper advice submission."""

    tracking_number: str = Field(min_length=1, max_length=100)
    advice_text: str = Field(min_length=1, max_length=5000)


@dataclass(frozen=True)
class ShipperAdviceResult:
    """Audit-friendly result of a shipper advice operation."""

    tracking_number: str
    submitted: bool
    submitted_at: datetime | None


class ShipperAdvicePage(Protocol):
    """Portal page capability used by the business workflow."""

    def find_pending(self) -> tuple[str, ...]:
        """Return pending tracking numbers."""

    def submit(self, action: ShipperAdviceAction) -> None:
        """Submit one validated action."""

    def verify_submission(self, action: ShipperAdviceAction) -> bool:
        """Verify that the portal accepted the action."""


class MPortalShipperAdvicePage:
    """M&P-specific shipper advice adapter with resilient actions."""

    def __init__(
        self,
        page: Page,
        advice_url: str,
        recovery: RecoveryProtocol | None = None,
        action_timeout_ms: int = 3500,
        recovery_max_retries: int = 3,
    ) -> None:
        if not advice_url.strip():
            raise ValueError("MP_SHIPPER_ADVICE_URL is required")
        self._page = page
        self._advice_url = advice_url.strip()
        self._actions = ResilientActions(
            page,
            recovery=recovery,
            timeout_ms=action_timeout_ms,
            max_retries=recovery_max_retries,
        )

    def open(self) -> None:
        self._actions.execute(
            ActionType.NAVIGATE,
            value=self._advice_url,
            target_description="open shipper advice URL",
        )

    def find_pending(self) -> tuple[str, ...]:
        self.open()
        pending: list[str] = []
        try:
            rows = self._page.locator(PortalSelectors.SHIPPER_ADVICE_ROW.candidates[0])
            for row in rows.all():
                text = row.inner_text().strip()
                if text:
                    pending.append(text.split()[0])
        except Exception:
            pass
        if pending:
            return tuple(pending)

        marker = self._page.locator(PortalSelectors.SHIPPER_ADVICE_PENDING.candidates[0])
        try:
            if marker.count() > 0:
                return tuple(
                    item.strip()
                    for item in marker.all_inner_texts()
                    if item.strip()
                )
        except Exception:
            return ()
        return ()

    def submit(self, action: ShipperAdviceAction) -> None:
        self.open()
        try:
            self._actions.execute(
                ActionType.FILL,
                PortalSelectors.TRACKING_INPUT,
                value=action.tracking_number,
                target_description="fill shipper advice tracking number",
            )
        except Exception:
            pass

        selected = False
        try:
            self._actions.execute(
                ActionType.SELECT,
                PortalSelectors.SHIPPER_ADVICE_INSTRUCTION,
                value=action.advice_text,
                target_description="select shipper advice instruction",
            )
            selected = True
        except Exception:
            selected = False

        if not selected:
            try:
                self._actions.execute(
                    ActionType.CLICK,
                    f'text="{action.advice_text}"',
                    target_description="click shipper advice instruction",
                )
                selected = True
            except Exception:
                selected = False

        if not selected:
            self._actions.execute(
                ActionType.FILL,
                PortalSelectors.SHIPPER_ADVICE_INPUT,
                value=action.advice_text,
                target_description="fill shipper advice text",
            )

        self._actions.execute(
            ActionType.CLICK,
            PortalSelectors.SHIPPER_ADVICE_SUBMIT,
            target_description="submit shipper advice",
            verify=lambda page: self._submission_visible(page),
        )

    def verify_submission(self, action: ShipperAdviceAction) -> bool:
        del action
        marker = PortalSelectors.SHIPPER_ADVICE_SUCCESS
        for selector in marker.candidates:
            try:
                if self._page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _submission_visible(page: Page) -> bool:
        for selector in PortalSelectors.SHIPPER_ADVICE_SUCCESS.candidates:
            try:
                locator = page.locator(selector).first
                if locator.count() and locator.is_visible():
                    return True
            except Exception:
                continue
        return False
