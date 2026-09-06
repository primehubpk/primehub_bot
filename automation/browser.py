"""Playwright browser lifecycle management."""
from __future__ import annotations

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from rehan_bot.config import Settings

from .session import SessionManager

class BrowserManager:
    """Own the Playwright process and recreate browser contexts safely."""

    def __init__(self, settings: Settings, session: SessionManager) -> None:
        self._settings = settings
        self._session = session
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    def start(self) -> BrowserContext:
        """Start Playwright and create the initial context."""
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        if self._browser is None:
            self._browser = self._playwright.chromium.launch(
                headless=self._settings.browser_headless
            )
        return self.recreate_context()

    def recreate_context(self) -> BrowserContext:
        """Replace the current context with a clean one."""
        if self._browser is None:
            raise RuntimeError("BrowserManager.start() must be called first")
        if self._context is not None:
            self._context.close()

        kwargs: dict[str, object] = {
            "viewport": {"width": 1440, "height": 900},
        }
        if self._session.exists:
            if self._session.is_valid_file():
                kwargs["storage_state"] = str(self._session.path)
            else:
                self._session.remove_corrupt()

        self._context = self._browser.new_context(**kwargs)
        self._context.set_default_timeout(self._settings.browser_timeout_ms)
        self._context.set_default_navigation_timeout(
            self._settings.navigation_timeout_ms
        )
        return self._context

    def new_page(self) -> Page:
        """Create a page in the active context."""
        if self._context is None:
            self.start()
        assert self._context is not None
        return self._context.new_page()

    @property
    def context(self) -> BrowserContext:
        """Return the active context."""
        if self._context is None:
            raise RuntimeError("Browser context is not started")
        return self._context

    def close(self) -> None:
        """Close Playwright resources in dependency order."""
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def __enter__(self) -> "BrowserManager":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
