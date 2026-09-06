"""Universal resilient Playwright action wrapper with self-healing."""
from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Protocol

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from rehan_bot.automation.diagnostics import DiagnosticCapture
from rehan_bot.portal.exceptions import SelectorNotFound, TerminalActionError
from rehan_bot.portal.selectors import PortalSelectors, SelectorSet


class ActionType(str, Enum):
    """Supported deterministic browser operations."""

    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    NAVIGATE = "navigate"
    READ = "read"


class RecoveryProtocol(Protocol):
    """Optional AI recovery capability used after deterministic failure."""

    def recover(self, page: Page, operation: str, error: Exception) -> bool:
        """Attempt recovery; return True when the caller should retry."""


def autonomous_execute(
    page: Page,
    goal_description: str,
    fallback_selector: str | SelectorSet | None = None,
    action: ActionType | str = ActionType.CLICK,
    value: str | None = None,
    *,
    recovery: RecoveryProtocol | None = None,
    verify: Callable[[Page], bool] | None = None,
    timeout_ms: int = 3_000,
    max_visual_iterations: int = 3,
) -> Locator | str | None:
    """Public universal action wrapper with deterministic-first visual recovery."""
    return ResilientActions(
        page, recovery=recovery, timeout_ms=timeout_ms, max_retries=max_visual_iterations
    ).execute(action, fallback_selector, target_description=goal_description, value=value, verify=verify)


class ResilientActions:
    """Central self-healing wrapper around Playwright actions."""

    def __init__(
        self,
        page: Page,
        recovery: RecoveryProtocol | None = None,
        timeout_ms: int = 1500,
        max_retries: int = 3,
        diagnostics: DiagnosticCapture | None = None,
    ) -> None:
        self._page = page
        self._recovery = recovery
        self._timeout_ms = timeout_ms
        self._max_retries = max(1, max_retries)
        self._diagnostics = diagnostics or DiagnosticCapture()

    def execute(
        self,
        action_type: ActionType | str,
        selector: str | SelectorSet | None = None,
        *,
        target_description: str,
        value: str | None = None,
        child_selector: str | None = None,
        verify: Callable[[Page], bool] | None = None,
    ) -> Locator | str | None:
        """Run one action with overlay handling, toggle guards, and AI retry."""

        action = ActionType(action_type)
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                self.dismiss_overlays()
                result = self._perform(
                    action,
                    selector,
                    value=value,
                    child_selector=child_selector,
                )
                if verify is not None and not verify(self._page):
                    raise TerminalActionError(
                        f"Post-condition failed after {target_description}"
                    )
                return result
            except Exception as error:
                last_error = error
                snapshot = self._diagnostics.capture(
                    self._page,
                    f"{action.value}_{attempt + 1}_{target_description}",
                )
                # First failed interaction is enough evidence to capture the
                # viewport and ask vision. Waiting through repeated selector
                # retries is the source of the old "stuck" behaviour.
                if self._recovery is None:
                    continue
                recovered = False
                try:
                    repair = getattr(self._recovery, "repair", None)
                    if callable(repair):
                        recovered = bool(repair(self._page, target_description))
                    else:
                        recovered = bool(self._recovery.recover(self._page, target_description, error))
                except Exception:
                    recovered = False
                if not recovered:
                    continue
                try:
                    self._page.wait_for_timeout(400)
                except Exception:
                    pass
                # A visual action may already have completed the requested
                # interaction. Do not blindly repeat a click (which can close
                # a dropdown or submit a form twice). Prefer the explicit
                # post-condition; otherwise accept a changed viewport state.
                try:
                    if verify is not None and verify(self._page):
                        return None
                    if verify is None:
                        after = self._diagnostics.capture(self._page, f"visual_verified_{target_description}")
                        if after.screenshot and after.screenshot != snapshot.screenshot:
                            return None
                except Exception:
                    pass

        raise TerminalActionError(
            f"Exhausted retries for {target_description}: {last_error}"
        ) from last_error

    def first_visible(self, selector_set: SelectorSet, timeout_ms: int | None = None) -> Locator:
        """Return the first visible locator from an ordered selector set."""
        timeout = timeout_ms or self._timeout_ms
        # Probe alternatives quickly. Waiting the full action timeout for every
        # missing selector turns a single failed field lookup into 20+ seconds.
        probe_timeout = max(80, min(250, timeout // max(1, len(selector_set.candidates))))
        for selector in selector_set.candidates:
            locator = self._page.locator(selector).first
            if self._usable(locator, probe_timeout):
                return locator
        raise SelectorNotFound(f"No usable selector found: {selector_set.candidates!r}")

    def dismiss_overlays(self) -> None:
        """Close announcement/scam/modal overlays that block clicks."""
        try:
            self._page.keyboard.press("Escape")
        except Exception:
            pass
        for selector in PortalSelectors.OVERLAY_CLOSE.candidates:
            locator = self._page.locator(selector).first
            try:
                # This runs before every action, so it must never wait for a
                # popup that does not exist. A visible popup is handled now;
                # an uncertain screen escalates to Vision after the action.
                if locator.count() > 0 and locator.is_visible():
                    locator.click(timeout=500, force=True)
                    self._page.wait_for_timeout(100)
            except Exception:
                continue

    def _perform(
        self,
        action: ActionType,
        selector: str | SelectorSet | None,
        *,
        value: str | None,
        child_selector: str | None,
    ) -> Locator | str | None:
        if action is ActionType.NAVIGATE:
            if not value:
                raise ValueError("Navigate requires a URL")
            self._page.goto(value, wait_until="domcontentloaded", timeout=self._timeout_ms * 4)
            return self._page.url

        locator = self._resolve(selector)
        if action is ActionType.CLICK:
            self._click(locator, child_selector)
            return locator
        if action is ActionType.FILL:
            if value is None:
                raise ValueError("Fill requires a value")
            locator.fill(value, timeout=self._timeout_ms)
            return locator
        if action is ActionType.SELECT:
            if value is None:
                raise ValueError("Select requires a value")
            locator.select_option(value, timeout=self._timeout_ms)
            return locator
        if action is ActionType.READ:
            return locator.inner_text(timeout=self._timeout_ms)
        raise ValueError(f"Unsupported action: {action}")

    def _resolve(self, selector: str | SelectorSet | None) -> Locator:
        if selector is None:
            raise SelectorNotFound("Action requires a selector")
        if isinstance(selector, SelectorSet):
            return self.first_visible(selector)
        locator = self._page.locator(selector).first
        if not self._usable(locator, self._timeout_ms):
            raise SelectorNotFound(f"Selector is not usable: {selector}")
        return locator

    def _click(self, locator: Locator, child_selector: str | None) -> None:
        if child_selector or self._looks_like_menu(locator):
            self._click_menu(locator, child_selector)
            return
        try:
            locator.scroll_into_view_if_needed(timeout=self._timeout_ms)
        except Exception:
            pass
        locator.click(timeout=self._timeout_ms)

    def _click_menu(self, locator: Locator, child_selector: str | None) -> None:
        """Expand a dropdown only when its children are hidden (no toggle loop)."""
        child = self._page.locator(child_selector).first if child_selector else None
        if child is not None and self._usable(child, 600):
            child.click(timeout=self._timeout_ms)
            return

        if self._is_expanded(locator) and child is None:
            return

        if not self._is_expanded(locator):
            locator.click(timeout=self._timeout_ms)
            try:
                self._page.wait_for_timeout(250)
            except Exception:
                pass

        if child is None:
            return
        if self._usable(child, self._timeout_ms):
            child.click(timeout=self._timeout_ms)
            return
        raise SelectorNotFound(f"Menu child is not visible: {child_selector}")

    def _looks_like_menu(self, locator: Locator) -> bool:
        try:
            return (
                locator.get_attribute("aria-expanded", timeout=400) is not None
                or locator.get_attribute("aria-haspopup", timeout=400) is not None
            )
        except Exception:
            return False

    def _is_expanded(self, locator: Locator) -> bool:
        try:
            expanded = (locator.get_attribute("aria-expanded", timeout=400) or "").lower()
            if expanded == "true":
                return True
            if expanded == "false":
                return False
        except Exception:
            pass
        try:
            menu = locator.locator(
                "xpath=following-sibling::*[contains(@class,'dropdown') or contains(@class,'menu') or self::ul][1]"
            ).first
            return self._usable(menu, 400)
        except Exception:
            return False

    def _usable(self, locator: Locator, timeout_ms: int) -> bool:
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator.count() > 0 and locator.is_visible()
        except PlaywrightTimeoutError:
            return False
        except Exception:
            try:
                return locator.count() > 0 and locator.is_visible()
            except Exception:
                return False
