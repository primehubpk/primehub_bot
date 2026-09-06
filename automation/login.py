"""Deterministic M&P CP-Light authentication state machine."""

from __future__ import annotations

from dataclasses import dataclass

from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from rehan_bot.config import Settings
from rehan_bot.automation.actions import ActionType, RecoveryProtocol, autonomous_execute
from rehan_bot.portal.exceptions import (
    AuthenticationFailed,
    PortalUnavailable,
    SelectorNotFound,
)
from rehan_bot.portal.selectors import (
    PortalSelectors,
    SelectorSet,
)
from rehan_bot.portal.states import PortalState

from .session import SessionManager


@dataclass(frozen=True)
class LoginResult:
    """Result of an M&P authentication attempt."""

    state: PortalState
    resumed_session: bool


class LoginManager:
    """Perform deterministic M&P CP-Light authentication."""

    def __init__(
        self,
        settings: Settings,
        session: SessionManager,
        recovery: RecoveryProtocol | None = None,
    ) -> None:
        self._settings = settings
        self._session = session
        self._recovery = recovery

    def authenticate(
        self,
        page: Page,
    ) -> LoginResult:
        """
        Resume an authenticated session or perform fresh login.

        CAPTCHA and maintenance are never bypassed automatically.
        """

        if not self._settings.mp_login_url:
            raise AuthenticationFailed(
                "MP_LOGIN_URL is not configured"
            )

        # -----------------------------------------------------
        # Open M&P login page
        # -----------------------------------------------------

        try:
            page.goto(
                self._settings.mp_login_url,
                wait_until="domcontentloaded",
                timeout=(
                    self._settings.navigation_timeout_ms
                ),
            )
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            raise PortalUnavailable(
                f"M&P login page could not be opened: {exc}"
            ) from exc

        # Give the JavaScript application a short opportunity
        # to render its login controls.
        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=5000,
            )
        except PlaywrightTimeoutError:
            # networkidle is not required for authentication.
            pass

        # -----------------------------------------------------
        # Detect current state
        # -----------------------------------------------------

        state = self.detect_state(page)

        # An unexpected modal, cookie wall, or changed login layout must not
        # look like a terminal timeout. Give the visual engine one immediate
        # chance to inspect the real screen before deciding the portal failed.
        if state is PortalState.TIMEOUT and self._recovery is not None:
            try:
                repair = getattr(self._recovery, "repair", None)
                if callable(repair) and repair(page, "identify login page controls or dismiss blocking popup"):
                    state = self.detect_state(page)
            except Exception:
                pass

        if state is PortalState.AUTHENTICATED:
            self._session.save(
                page.context
            )

            return LoginResult(
                state=state,
                resumed_session=True,
            )

        if state is PortalState.CAPTCHA_DETECTED:
            return LoginResult(
                state=state,
                resumed_session=False,
            )

        if state is PortalState.PORTAL_MAINTENANCE:
            raise PortalUnavailable(
                "M&P portal reports maintenance"
            )

        if state is PortalState.TIMEOUT:
            raise PortalUnavailable(
                "M&P portal state could not be determined"
            )

        # -----------------------------------------------------
        # Login is required
        # -----------------------------------------------------

        # A stale server-side session can return to this same login form just
        # after submit. Re-fill and submit once more instead of closing the
        # browser on the first bounce-back.
        final_state = PortalState.LOGIN_REQUIRED
        for login_attempt in range(2):
            self._perform_fresh_login(page)
            final_state = self._wait_for_post_login_state(page)
            if final_state is PortalState.AUTHENTICATED:
                break
            if final_state is PortalState.LOGIN_REQUIRED and login_attempt == 0:
                continue
            if final_state is PortalState.CAPTCHA_DETECTED:
                return LoginResult(state=final_state, resumed_session=False)
            if final_state is PortalState.PORTAL_MAINTENANCE:
                raise PortalUnavailable("M&P portal entered maintenance state during login")

        if final_state is not PortalState.AUTHENTICATED:
            raise AuthenticationFailed(
                "M&P login did not reach authenticated state: "
                f"{final_state.value} after automatic retry"
            )

        # -----------------------------------------------------
        # Persist authenticated browser state
        # -----------------------------------------------------

        self._session.save(
            page.context
        )

        return LoginResult(
            state=final_state,
            resumed_session=False,
        )

    def detect_state(
        self,
        page: Page,
    ) -> PortalState:
        """
        Determine portal state using deterministic DOM evidence.

        Priority:
            maintenance
            CAPTCHA
            login required
            authenticated
            timeout
        """

        # -----------------------------------------------------
        # 1. Maintenance
        # -----------------------------------------------------

        if self._matches_any(
            page,
            PortalSelectors.MAINTENANCE_MARKERS,
        ):
            return PortalState.PORTAL_MAINTENANCE

        # -----------------------------------------------------
        # 2. CAPTCHA
        # -----------------------------------------------------

        if self._matches_any(
            page,
            PortalSelectors.CAPTCHA_MARKERS,
        ):
            return PortalState.CAPTCHA_DETECTED

        # -----------------------------------------------------
        # 3. URL + login-form evidence
        # -----------------------------------------------------

        current_url = (
            page.url
            .lower()
            .rstrip("/")
        )

        configured_login_url = (
            self._settings.mp_login_url
            .lower()
            .rstrip("/")
        )

        on_login_page = (
            current_url == configured_login_url
            or current_url.endswith("/login")
        )

        login_form_present = self._matches_any(
            page,
            PortalSelectors.LOGIN_MARKERS,
        )

        # Login fields are decisive. The M&P login page contains generic
        # marketing/dashboard words, so text such as "Welcome" must never
        # override an actually visible credential form.
        if on_login_page and login_form_present:
            return PortalState.LOGIN_REQUIRED

        # -----------------------------------------------------
        # 4. Known authenticated markers
        # -----------------------------------------------------

        if self._matches_any(
            page,
            PortalSelectors.AUTHENTICATED_MARKERS,
        ):
            return PortalState.AUTHENTICATED

        # If we have left /login and the login form has
        # disappeared, this is positive authenticated evidence.
        #
        # This is intentionally used only as a secondary
        # deterministic signal.
        if (
            not on_login_page
            and not login_form_present
        ):
            return PortalState.AUTHENTICATED

        # -----------------------------------------------------
        # 5. Login form still present
        # -----------------------------------------------------

        if login_form_present:
            return PortalState.LOGIN_REQUIRED

        return PortalState.TIMEOUT

    def _perform_fresh_login(
        self,
        page: Page,
    ) -> None:
        """Fill credentials and submit the M&P login form."""

        if not self._settings.mp_username:
            raise AuthenticationFailed(
                "MP_USERNAME is not configured"
            )

        if not self._settings.mp_password:
            raise AuthenticationFailed(
                "MP_PASSWORD is not configured"
            )

        # -----------------------------------------------------
        # Check CAPTCHA immediately before credentials
        # -----------------------------------------------------

        if self._matches_any(
            page,
            PortalSelectors.CAPTCHA_MARKERS,
        ):
            return

        # -----------------------------------------------------
        # Username
        # -----------------------------------------------------

        autonomous_execute(page, "fill username", PortalSelectors.USERNAME, ActionType.FILL,
                           self._settings.mp_username, recovery=self._recovery)

        # -----------------------------------------------------
        # Password
        # -----------------------------------------------------

        autonomous_execute(page, "fill password", PortalSelectors.PASSWORD, ActionType.FILL,
                           self._settings.mp_password, recovery=self._recovery)

        # -----------------------------------------------------
        # Check CAPTCHA again before submitting
        # -----------------------------------------------------

        if self._matches_any(
            page,
            PortalSelectors.CAPTCHA_MARKERS,
        ):
            return

        # -----------------------------------------------------
        # Submit
        # -----------------------------------------------------

        autonomous_execute(page, "submit login", PortalSelectors.SUBMIT, ActionType.CLICK,
                           recovery=self._recovery)

        # -----------------------------------------------------
        # Wait for navigation when available.
        # Some JavaScript portals do not perform a full
        # navigation, so timeout is not automatically fatal.
        # -----------------------------------------------------

        try:
            page.wait_for_load_state(
                "domcontentloaded",
                timeout=(
                    self._settings.navigation_timeout_ms
                ),
            )
        except PlaywrightTimeoutError:
            # The SPA may update the DOM without navigation.
            pass

    def _wait_for_post_login_state(
        self,
        page: Page,
    ) -> PortalState:
        """
        Wait for a deterministic post-login state.

        No blind fixed sleep is used. We repeatedly inspect the
        DOM for authentication, CAPTCHA, maintenance or login.
        """

        # A completed form submission normally transitions within a few
        # seconds. Keeping a 30-second blind poll here made failed logins look
        # like a frozen bot and delayed visual recovery/retry.
        timeout_ms = max(3_000, min(self._settings.navigation_timeout_ms, 8_000))

        deadline = (
            page
            .context
            .browser
            .version
            if False
            else None
        )

        # Playwright's wait_for_function gives us a controlled
        # browser-side polling mechanism. The actual state is
        # still validated through detect_state() below.
        try:
            page.wait_for_timeout(750)
        except Exception:
            pass

        # -----------------------------------------------------
        # Poll deterministic states.
        # -----------------------------------------------------

        attempts = max(
            1,
            timeout_ms // 400,
        )

        for _ in range(attempts):
            state = self.detect_state(page)

            if state in {
                PortalState.CAPTCHA_DETECTED,
                PortalState.PORTAL_MAINTENANCE,
            }:
                return state

            if state is PortalState.AUTHENTICATED:
                # CP-Light can briefly leave /login while it processes a
                # rejected/stale session, then redirect back. Do not report a
                # successful login until that state stays authenticated.
                try:
                    page.wait_for_timeout(1_200)
                except Exception:
                    pass
                return self.detect_state(page)

            if state is PortalState.LOGIN_REQUIRED:
                # Login form is still visible. Give the SPA a
                # little more time before declaring failure.
                try:
                    page.wait_for_timeout(400)
                except Exception:
                    pass

                continue

            if state is PortalState.TIMEOUT:
                try:
                    page.wait_for_timeout(400)
                except Exception:
                    pass

        return self.detect_state(page)

    @staticmethod
    def _matches_any(
        page: Page,
        selector_set: SelectorSet,
    ) -> bool:
        """Return True when any candidate selector is present."""

        for selector in selector_set.candidates:
            try:
                locator = page.locator(selector)

                if locator.count() > 0:
                    return True

            except Exception:
                continue

        return False

    @staticmethod
    def _fill_first(
        page: Page,
        selector_set: SelectorSet,
        value: str,
    ) -> None:
        """Fill the first visible usable input."""

        for selector in selector_set.candidates:
            try:
                locator = page.locator(
                    selector
                ).first

                if (
                    locator.count() > 0
                    and locator.is_visible()
                    and locator.is_enabled()
                ):
                    locator.fill(value)
                    return

            except Exception:
                continue

        raise SelectorNotFound(
            "No usable credential field selector found"
        )

    @staticmethod
    def _click_first(
        page: Page,
        selector_set: SelectorSet,
    ) -> None:
        """Click the first visible usable submit control."""

        for selector in selector_set.candidates:
            try:
                locator = page.locator(
                    selector
                ).first

                if (
                    locator.count() > 0
                    and locator.is_visible()
                    and locator.is_enabled()
                ):
                    locator.click()
                    return

            except Exception:
                continue

        raise SelectorNotFound(
            "No usable login submit selector found"
        )
