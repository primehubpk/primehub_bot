"""M&P portal client orchestration boundary."""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

from rehan_bot.automation.browser import BrowserManager
from rehan_bot.automation.login import LoginManager, LoginResult
from rehan_bot.automation.session import SessionManager
from rehan_bot.config import Settings
from rehan_bot.automation.actions import RecoveryProtocol

class PortalClient:
    """Coordinate browser, session, and deterministic authentication."""

    def __init__(self, settings: Settings, session_file: Path, recovery: RecoveryProtocol | None = None) -> None:
        self._session = SessionManager(session_file)
        self._browser = BrowserManager(settings, self._session)
        self._login = LoginManager(settings, self._session, recovery=recovery)
        self._page: Page | None = None

    def start(self) -> None:
        """Start the browser and create a working page."""
        self._browser.start()
        self._page = self._browser.new_page()

    def login(self) -> LoginResult:
        """Authenticate the current page."""
        if self._page is None:
            raise RuntimeError("PortalClient.start() must be called first")
        return self._login.authenticate(self._page)

    @property
    def page(self) -> Page:
        """Return the active page."""
        if self._page is None:
            raise RuntimeError("PortalClient.start() must be called first")
        return self._page

    def recreate_context(self) -> None:
        """Recreate context/page after a browser-level failure."""
        self._browser.recreate_context()
        self._page = self._browser.new_page()

    def close(self) -> None:
        """Close browser resources."""
        self._page = None
        self._browser.close()

    def __enter__(self) -> "PortalClient":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
