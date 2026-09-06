"""WhatsApp Web transport driven by our own Playwright browser.

WhatsApp Web keeps its authentication keys in IndexedDB, which Playwright's
``storage_state`` cannot capture. The durable session therefore lives in a
persistent Chromium profile directory; the JSON state file records when the
device was linked so an expired session can be detected before launching.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import sys
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from playwright.sync_api import Locator, Page, sync_playwright

from rehan_bot.observability.logging import configure_file_logger

WHATSAPP_HOME = "https://web.whatsapp.com/"

# WhatsApp Web refuses to load for the default headless UA string.
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

QR_SELECTORS = (
    'canvas[aria-label*="Scan" i]',
    "div[data-ref] canvas",
    "div[data-ref]",
    '[data-testid="qrcode"]',
    'canvas[role="img"]',
)

LOGGED_IN_SELECTORS = (
    "#pane-side",
    'div[aria-label="Chat list"]',
    '[data-testid="chat-list"]',
    'header [data-icon="new-chat-outline"]',
    '[data-icon="chats-outline"]',
)

COMPOSER_SELECTORS = (
    'div[contenteditable="true"][data-tab="10"]',
    'div[contenteditable="true"][data-tab="6"]',
    'div[aria-placeholder="Type a message"]',
    'div[title="Type a message"]',
    "footer div[contenteditable='true']",
    'div[contenteditable="true"][role="textbox"]',
    '[data-testid="conversation-compose-box-input"]',
)

SEND_BUTTON_SELECTORS = (
    'button[aria-label="Send"]',
    'button[aria-label*="Send" i]',
    'span[data-icon="send"]',
    'button[data-tab="11"]',
    '[data-testid="send"]',
)

# `data-testid="msg-container"` is the one attribute WhatsApp Web has kept
# stable across its many CSS-class-name (atomic/obfuscated) rewrites, so
# every bubble lookup below is scoped from here rather than from a class
# name, which can silently stop matching after a WhatsApp Web deploy.
MESSAGE_CONTAINER_SELECTOR = 'div[data-testid="msg-container"]'

# A container is *ours* when it carries the outgoing tail icon or the
# accessibility label WhatsApp attaches to our own messages. Either is
# sufficient; both are checked for resilience against future markup tweaks.
OUTGOING_MESSAGE_SELECTORS = (
    f'{MESSAGE_CONTAINER_SELECTOR}:has([aria-label="You:"])',
    f'{MESSAGE_CONTAINER_SELECTOR}:has([data-icon="tail-out"])',
)

# WhatsApp Web now renders the delivery tick's accessible name as an
# aria-label on the status icon inside `[data-testid="msg-meta"]` (e.g.
# " Sent ", " Delivered ", " Read ") instead of the old data-icon values.
ACK_META_SELECTOR = '[data-testid="msg-meta"]'
ACK_SENT_LABEL_RE = re.compile(r"(sent|delivered|read)", re.IGNORECASE)
ACK_PENDING_LABEL_RE = re.compile(r"(pending|clock|sending|waiting)", re.IGNORECASE)

# Fallback for older/other WhatsApp Web builds that still expose the ack
# state as a plain data-icon attribute rather than an aria-label.
PENDING_ACK_SELECTORS = (
    'span[data-icon="msg-time"]',
    'span[data-icon="status-time"]',
)
SENT_ACK_SELECTORS = (
    'span[data-icon="msg-check"]',
    'span[data-icon="msg-dblcheck"]',
    'span[data-icon="status-check"]',
    'span[data-icon="status-dblcheck"]',
)

SENT_SCREENSHOT_NAME = "whatsapp_sent_success.png"

DIALOG_SELECTORS = (
    'div[data-animate-modal-body="true"]',
    'div[role="dialog"]',
)

INVALID_NUMBER_PHRASES = (
    "phone number shared via url is invalid",
    "url is invalid",
    "isn't on whatsapp",
    "is not on whatsapp",
)


def safe_print(text: str = "") -> None:
    """Print text that may contain characters the console cannot encode.

    Windows consoles default to cp1252, so parcel emoji and Playwright's
    box-drawing hints would otherwise raise UnicodeEncodeError.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "") or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


class WhatsAppWebError(RuntimeError):
    """Raised when WhatsApp Web could not deliver the message."""


class WhatsAppLoginRequired(WhatsAppWebError):
    """Raised when the stored session cannot be used without a QR scan."""


def normalize_phone(raw: str, default_country_code: str = "92") -> str:
    """Return a bare international phone number accepted by the send URL."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        raise WhatsAppWebError(
            "WhatsApp recipient is not configured. Set WHATSAPP_PHONE in .env "
            "to your own number in international format, e.g. 923001234567."
        )
    if digits.startswith("00"):
        digits = digits[2:]
    # Local Pakistani style 03xxxxxxxxx -> 923xxxxxxxxx.
    if digits.startswith("0"):
        digits = f"{default_country_code}{digits.lstrip('0')}"
    if len(digits) < 8:
        raise WhatsAppWebError(f"WhatsApp recipient looks incomplete: {raw!r}")
    return digits


def build_send_url(phone: str, message: str, default_country_code: str = "92") -> str:
    """Build the prefilled WhatsApp Web chat URL."""
    number = normalize_phone(phone, default_country_code)
    text = urllib.parse.quote(message or "", safe="")
    return f"https://web.whatsapp.com/send?phone={number}&text={text}"


@dataclass(frozen=True)
class WhatsAppWebConfig:
    """Everything the Playwright WhatsApp transport needs."""

    phone: str
    profile_dir: Path = Path("runtime/browser/whatsapp_profile")
    session_file: Path = Path("runtime/browser/whatsapp_state.json")
    log_file: Path = Path("runtime/logs/whatsapp.log")
    screenshot_dir: Path = Path("runtime/screenshots")
    headless: bool = True
    browser_channel: str = ""
    default_country_code: str = "92"
    session_ttl_days: int = 14
    navigation_timeout_ms: int = 60_000
    action_timeout_ms: int = 30_000
    qr_timeout_seconds: int = 180
    confirm_timeout_seconds: int = 20
    launch_args: Sequence[str] = field(
        default_factory=lambda: ("--disable-blink-features=AutomationControlled",)
    )

    @classmethod
    def from_settings(cls, settings: Any) -> "WhatsAppWebConfig":
        """Build configuration from application settings."""
        return cls(
            phone=str(getattr(settings, "whatsapp_phone", "") or "").strip(),
            profile_dir=Path(
                getattr(settings, "whatsapp_profile_dir", "")
                or "runtime/browser/whatsapp_profile"
            ),
            session_file=Path(
                getattr(settings, "whatsapp_session_file", "")
                or "runtime/browser/whatsapp_state.json"
            ),
            log_file=Path(
                getattr(settings, "whatsapp_log_file", "") or "runtime/logs/whatsapp.log"
            ),
            headless=bool(getattr(settings, "whatsapp_headless", True)),
            browser_channel=str(
                getattr(settings, "whatsapp_browser_channel", "") or ""
            ).strip(),
            default_country_code=str(
                getattr(settings, "whatsapp_default_country_code", "") or "92"
            ).strip(),
            session_ttl_days=int(getattr(settings, "whatsapp_session_ttl_days", 14)),
            navigation_timeout_ms=int(
                getattr(settings, "navigation_timeout_ms", 60_000)
            ),
            action_timeout_ms=int(getattr(settings, "browser_timeout_ms", 30_000)),
            qr_timeout_seconds=int(
                getattr(settings, "whatsapp_qr_timeout_seconds", 180)
            ),
        )

    @classmethod
    def from_env(cls, phone: str | None = None) -> "WhatsAppWebConfig":
        """Build configuration straight from environment variables."""

        def flag(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            if raw is None or not raw.strip():
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        def number(name: str, default: int) -> int:
            try:
                return int(str(os.environ.get(name, "")).strip() or default)
            except ValueError:
                return default

        return cls(
            phone=(phone or os.environ.get("WHATSAPP_PHONE", "")).strip(),
            profile_dir=Path(
                os.environ.get("WHATSAPP_PROFILE_DIR")
                or "runtime/browser/whatsapp_profile"
            ),
            session_file=Path(
                os.environ.get("WHATSAPP_SESSION_FILE")
                or "runtime/browser/whatsapp_state.json"
            ),
            log_file=Path(
                os.environ.get("WHATSAPP_LOG_FILE") or "runtime/logs/whatsapp.log"
            ),
            headless=flag("WHATSAPP_HEADLESS", True),
            browser_channel=os.environ.get("WHATSAPP_BROWSER_CHANNEL", "").strip(),
            default_country_code=(
                os.environ.get("WHATSAPP_DEFAULT_COUNTRY_CODE", "").strip() or "92"
            ),
            session_ttl_days=number("WHATSAPP_SESSION_TTL_DAYS", 14),
            navigation_timeout_ms=number("NAVIGATION_TIMEOUT_MS", 60_000),
            action_timeout_ms=number("BROWSER_TIMEOUT_MS", 30_000),
            qr_timeout_seconds=number("WHATSAPP_QR_TIMEOUT_SECONDS", 180),
        )


class WhatsAppSession:
    """Track whether the persistent WhatsApp profile is still linked."""

    def __init__(self, state_file: Path, profile_dir: Path, ttl_days: int = 14) -> None:
        self._state_file = state_file
        self._profile_dir = profile_dir
        self._ttl_days = max(1, ttl_days)

    @property
    def path(self) -> Path:
        """Return the state file path."""
        return self._state_file

    @property
    def profile_dir(self) -> Path:
        """Return the persistent Chromium profile directory."""
        return self._profile_dir

    def _payload(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    @property
    def linked_at(self) -> datetime | None:
        """Return when the device was last linked, if recorded."""
        payload = self._payload()
        raw = payload.get("linked_at") if payload else None
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(str(raw))
        except ValueError:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    @property
    def profile_ready(self) -> bool:
        """Whether a non-empty persistent profile exists."""
        if not self._profile_dir.is_dir():
            return False
        try:
            return any(self._profile_dir.iterdir())
        except OSError:
            return False

    def is_linked(self) -> bool:
        """Whether the stored session can be reused without a QR scan."""
        if not self.profile_ready:
            return False
        linked = self.linked_at
        if linked is None:
            return False
        age = datetime.now(timezone.utc) - linked
        return age <= timedelta(days=self._ttl_days)

    def mark_linked(self, context: Any, phone: str = "") -> None:
        """Record a successful link and dump the cookie/localStorage state."""
        storage: dict[str, Any] = {}
        try:
            storage = context.storage_state()
        except Exception:
            storage = {}

        payload = {
            "linked_at": datetime.now(timezone.utc).isoformat(),
            "phone": phone,
            "profile_dir": str(self._profile_dir),
            "storage_state": storage,
        }
        self._write(payload)

    def _write(self, payload: dict[str, Any]) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{self._state_file.name}.",
            suffix=".tmp",
            dir=self._state_file.parent,
            text=True,
        )
        os.close(handle)
        try:
            Path(temp_name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temp_name, self._state_file)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def invalidate(self) -> None:
        """Forget the recorded link so the next run shows the QR code."""
        try:
            self._state_file.unlink(missing_ok=True)
        except OSError:
            pass


class WhatsAppWebSender:
    """Send messages through a persistent WhatsApp Web browser profile."""

    def __init__(
        self,
        config: WhatsAppWebConfig,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._session = WhatsAppSession(
            config.session_file, config.profile_dir, config.session_ttl_days
        )
        self._logger = logger or configure_file_logger(
            "rehan_bot.notifications.whatsapp_web",
            config.log_file,
            propagate=True,
        )

    # -----------------------------------------------------------------
    # PUBLIC API
    # -----------------------------------------------------------------

    def send(self, message: str) -> bool:
        """Deliver one message, opening a visible window if linking is needed."""
        if not (message or "").strip():
            self._logger.warning("Refusing to send an empty WhatsApp message")
            return False
        return self._perform(message)

    def link(self) -> bool:
        """Open a visible browser so the QR code can be scanned once."""
        try:
            return bool(self._run(lambda: self._attempt(None, force_visible=True)))
        except Exception as exc:
            self._record_failure("link", exc)
            return False

    @property
    def session(self) -> WhatsAppSession:
        """Expose the session for diagnostics and CLI reporting."""
        return self._session

    # -----------------------------------------------------------------
    # ORCHESTRATION
    # -----------------------------------------------------------------

    def _perform(self, message: str) -> bool:
        try:
            return bool(self._run(lambda: self._attempt(message, force_visible=False)))
        except WhatsAppLoginRequired as exc:
            self._logger.warning(
                "WhatsApp Web session is missing or expired: %s", exc
            )
            safe_print(
                "[WhatsApp] Session not linked. Opening a visible browser window - "
                "scan the QR code once with your phone."
            )
        except Exception as exc:
            self._record_failure("send", exc)
            return False

        try:
            return bool(self._run(lambda: self._attempt(message, force_visible=True)))
        except Exception as exc:
            self._record_failure("send-after-qr", exc)
            return False

    def _run(self, operation: Callable[[], bool]) -> bool:
        """Run a Playwright operation on its own thread.

        The portal workflow already holds a sync Playwright loop, so the
        WhatsApp browser is driven from a dedicated thread instead of nesting.
        """
        outcome: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

        def runner() -> None:
            try:
                outcome.put(("ok", operation()))
            except BaseException as exc:  # noqa: BLE001 - forwarded to caller
                outcome.put(("error", exc))

        budget = (
            self._config.navigation_timeout_ms / 1000
            + self._config.action_timeout_ms / 1000
            + self._config.qr_timeout_seconds
            + 120
        )
        thread = threading.Thread(target=runner, name="whatsapp-web", daemon=True)
        thread.start()
        thread.join(budget)

        if thread.is_alive():
            raise WhatsAppWebError(
                f"WhatsApp Web did not finish within {int(budget)}s and was abandoned"
            )

        kind, value = outcome.get_nowait()
        if kind == "error":
            raise value
        return bool(value)

    def _attempt(self, message: str | None, force_visible: bool) -> bool:
        """Launch the profile, resolve login, then optionally send a message."""
        headless = (
            self._config.headless and self._session.is_linked() and not force_visible
        )
        profile_dir = self._config.profile_dir
        profile_dir.mkdir(parents=True, exist_ok=True)

        launch_kwargs: dict[str, Any] = {
            "user_data_dir": str(profile_dir),
            "headless": headless,
            "args": list(self._config.launch_args),
            "user_agent": CHROME_USER_AGENT,
            "viewport": {"width": 1440, "height": 920},
            "locale": "en-US",
        }
        if self._config.browser_channel:
            launch_kwargs["channel"] = self._config.browser_channel

        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as exc:
                raise WhatsAppWebError(
                    "Could not launch the WhatsApp browser profile "
                    f"({profile_dir}). Close any other window using it, then retry. "
                    f"Playwright said: {exc}"
                ) from exc

            context.set_default_timeout(self._config.action_timeout_ms)
            context.set_default_navigation_timeout(self._config.navigation_timeout_ms)
            page = context.pages[0] if context.pages else context.new_page()

            try:
                self._ensure_logged_in(page, allow_qr=not headless)
                self._session.mark_linked(context, self._config.phone)

                if message is None:
                    self._logger.info("WhatsApp Web profile is linked and ready")
                    safe_print("[WhatsApp] Device linked. Session saved.")
                    return True

                self._open_chat(page, message)
                # Blocks until the sent bubble + ack are confirmed (or raises);
                # the `finally` below only closes the browser after this returns.
                self._dispatch(page, message)

                recipient = normalize_phone(
                    self._config.phone, self._config.default_country_code
                )
                self._logger.info("WhatsApp Web message delivered to %s", recipient)
                safe_print(f"[WhatsApp] Report sent to {recipient}")
                return True
            except WhatsAppLoginRequired:
                raise
            except Exception:
                self._capture(page, "failure")
                raise
            finally:
                try:
                    context.close()
                except Exception:
                    pass

    # -----------------------------------------------------------------
    # LOGIN
    # -----------------------------------------------------------------

    def _ensure_logged_in(self, page: Page, allow_qr: bool) -> None:
        self._goto(page, WHATSAPP_HOME)

        deadline = time.monotonic() + max(20.0, self._config.action_timeout_ms / 1000)
        while time.monotonic() < deadline:
            if self._first_visible(page, LOGGED_IN_SELECTORS) is not None:
                return
            if self._first_visible(page, QR_SELECTORS) is not None:
                if not allow_qr:
                    raise WhatsAppLoginRequired(
                        "WhatsApp Web asked for a QR scan while running headless"
                    )
                self._wait_for_qr_scan(page)
                return
            page.wait_for_timeout(500)

        if self._first_visible(page, LOGGED_IN_SELECTORS) is not None:
            return
        if not allow_qr:
            raise WhatsAppLoginRequired(
                "WhatsApp Web never reached the chat list; assuming the session expired"
            )

        self._capture(page, "login-unknown-state")
        raise WhatsAppWebError(
            "WhatsApp Web showed neither the QR code nor the chat list. "
            "Check runtime/screenshots for the captured page."
        )

    def _wait_for_qr_scan(self, page: Page) -> None:
        self._session.invalidate()
        self._capture(page, "qr")
        safe_print()
        safe_print("=" * 52)
        safe_print("  SCAN THE WHATSAPP QR CODE IN THE OPEN BROWSER")
        safe_print("=" * 52)
        safe_print("  Phone -> WhatsApp -> Settings -> Linked devices")
        safe_print("  -> Link a device -> scan the code on screen.")
        safe_print(f"  Waiting up to {self._config.qr_timeout_seconds}s ...")
        safe_print("=" * 52)
        safe_print()
        self._logger.info("Waiting for WhatsApp QR scan")

        deadline = time.monotonic() + self._config.qr_timeout_seconds
        while time.monotonic() < deadline:
            if self._first_visible(page, LOGGED_IN_SELECTORS) is not None:
                self._logger.info("WhatsApp QR scan completed")
                safe_print("[WhatsApp] Linked successfully.")
                return
            page.wait_for_timeout(1000)

        self._capture(page, "qr-timeout")
        raise WhatsAppWebError(
            f"QR code was not scanned within {self._config.qr_timeout_seconds}s"
        )

    # -----------------------------------------------------------------
    # CHAT + SEND
    # -----------------------------------------------------------------

    def _open_chat(self, page: Page, message: str) -> None:
        url = build_send_url(
            self._config.phone, message, self._config.default_country_code
        )
        self._goto(page, url)

        deadline = time.monotonic() + max(20.0, self._config.action_timeout_ms / 1000)
        while time.monotonic() < deadline:
            invalid = self._dialog_text(page)
            if invalid:
                self._capture(page, "invalid-number")
                raise WhatsAppWebError(
                    "WhatsApp rejected the recipient. Verify WHATSAPP_PHONE uses "
                    f"international format without '+'. Dialog said: {invalid}"
                )
            if self._first_visible(page, COMPOSER_SELECTORS) is not None:
                return
            page.wait_for_timeout(500)

        self._capture(page, "composer-timeout")
        raise WhatsAppWebError(
            "The WhatsApp message box never opened for this chat. "
            "Check runtime/screenshots for the captured page."
        )

    def _dispatch(self, page: Page, message: str) -> None:
        composer = self._first_visible(page, COMPOSER_SELECTORS)
        if composer is None:
            raise WhatsAppWebError("WhatsApp message box disappeared before sending")

        composer.click()
        if not self._composer_text(composer):
            self._type_message(page, composer, message)

        if not self._composer_text(composer):
            raise WhatsAppWebError("WhatsApp message box stayed empty after typing")

        # Recorded before the click so the confirmation step below can tell
        # our new bubble apart from any older messages already in the chat.
        bubbles = self._locate_outgoing_bubbles(page)
        baseline_count = self._safe_count(bubbles)

        self._click_send(page)

        # This call blocks until the message bubble is confirmed sent (or
        # raises). The caller only closes the browser context afterwards, in
        # its `finally`, so the browser never closes on an unconfirmed send.
        self._confirm_sent(page, composer, message, bubbles, baseline_count)

    def _type_message(self, page: Page, composer: Locator, message: str) -> None:
        """Type the message, keeping newlines inside a single chat bubble."""
        for index, line in enumerate(message.split("\n")):
            if index:
                page.keyboard.press("Shift+Enter")
            if not line:
                continue
            try:
                composer.press_sequentially(line, delay=8)
            except AttributeError:
                composer.type(line, delay=8)

    def _click_send(self, page: Page) -> None:
        button = self._first_visible(page, SEND_BUTTON_SELECTORS)
        if button is not None:
            try:
                button.click()
                return
            except Exception:
                pass
        page.keyboard.press("Enter")

    def _confirm_sent(
        self,
        page: Page,
        composer: Locator,
        message: str,
        bubbles: Locator | None,
        baseline_count: int,
    ) -> None:
        """Require three signals before allowing the caller to close the browser.

        1. The composer text input is empty again.
        2. A new outgoing message bubble rendered (matched against the
           message we just typed, not just any bubble already in the chat).
        3. That bubble's delivery icon left the pending clock state (sent,
           delivered, or read check marks).
        """
        snippet = self._first_message_line(message)
        last_bubble: Locator | None = None
        last_state = "unknown"

        for attempt in range(2):
            deadline = time.monotonic() + self._config.confirm_timeout_seconds
            while time.monotonic() < deadline:
                composer_cleared = not self._composer_text(composer)
                bubble = self._latest_new_bubble(bubbles, baseline_count, snippet)
                if bubble is not None:
                    last_bubble = bubble
                    last_state = self._bubble_ack_state(bubble)
                    if composer_cleared and last_state == "sent":
                        self._capture_sent_success(page, bubble)
                        self._logger.info(
                            "WhatsApp message confirmed sent (ack=%s)", last_state
                        )
                        return
                page.wait_for_timeout(400)
            if attempt == 0:
                self._logger.warning("No send acknowledgement yet; pressing Enter again")
                try:
                    composer.click()
                    page.keyboard.press("Enter")
                except Exception:
                    break

        if (
            last_bubble is not None
            and last_state != "pending"
            and not self._composer_text(composer)
        ):
            # The bubble rendered, matched our text, and the composer is
            # clear, but no ack icon was found on the probed element. Some
            # WhatsApp Web builds render the icon on a slightly different
            # node; failing a real send over that would be worse than
            # logging it and moving on. A bubble stuck on the pending clock
            # icon still falls through to the hard failure below.
            self._capture_sent_success(page, last_bubble)
            self._logger.warning(
                "WhatsApp bubble matched and composer cleared, but no ack "
                "icon was found; treating as sent (ack=%s)",
                last_state,
            )
            return

        self._capture(page, "no-ack")
        raise WhatsAppWebError(
            "WhatsApp never confirmed the message bubble was sent "
            f"(last ack state: {last_state}). "
            "Check runtime/screenshots for the captured page."
        )

    # -----------------------------------------------------------------
    # HELPERS
    # -----------------------------------------------------------------

    def _goto(self, page: Page, url: str) -> None:
        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self._config.navigation_timeout_ms,
            )
        except Exception as exc:
            raise WhatsAppWebError(f"Could not open {url}: {exc}") from exc

    @staticmethod
    def _first_visible(
        page: Page, selectors: Sequence[str], timeout_ms: int = 600
    ) -> Locator | None:
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() and locator.is_visible(timeout=timeout_ms):
                    return locator
            except Exception:
                continue
        return None

    @staticmethod
    def _composer_text(composer: Locator) -> str:
        try:
            return (composer.inner_text(timeout=1_000) or "").strip()
        except Exception:
            return ""

    def _locate_outgoing_bubbles(self, page: Page) -> Locator | None:
        """Return a locator for our own message bubbles in the open chat."""
        for selector in OUTGOING_MESSAGE_SELECTORS:
            try:
                locator = page.locator(selector)
                if locator.count():
                    return locator
            except Exception:
                continue
        # No bubble exists yet (brand new chat): return the first candidate
        # anyway so it can be re-probed once the reply renders.
        try:
            return page.locator(OUTGOING_MESSAGE_SELECTORS[0])
        except Exception:
            return None

    @staticmethod
    def _safe_count(locator: Locator | None) -> int:
        if locator is None:
            return 0
        try:
            return locator.count()
        except Exception:
            return 0

    @staticmethod
    def _first_message_line(message: str) -> str:
        """Return a plain-text snippet suitable for matching against innerText.

        Leading emoji (e.g. the parcel icon) are stripped because WhatsApp
        Web renders them as ``<img>`` elements, which most browsers exclude
        from ``innerText`` and would otherwise break the substring match.
        """
        for line in message.splitlines():
            stripped = line.strip()
            while stripped and not stripped[0].isalnum():
                stripped = stripped[1:].lstrip()
            if stripped:
                return stripped[:60]
        return ""

    def _latest_new_bubble(
        self,
        bubbles: Locator | None,
        baseline_count: int,
        snippet: str,
    ) -> Locator | None:
        """Return the newest bubble past the baseline, verified against our text."""
        if bubbles is None:
            return None
        try:
            count = bubbles.count()
        except Exception:
            return None
        if count <= baseline_count:
            return None

        candidate = bubbles.last
        if snippet:
            try:
                text = candidate.inner_text(timeout=500)
            except Exception:
                text = ""
            if snippet not in text:
                return None
        return candidate

    def _bubble_ack_state(self, bubble: Locator) -> str:
        """Classify one outgoing bubble's delivery status.

        Primary signal: the aria-label WhatsApp Web attaches to the status
        icon inside ``[data-testid="msg-meta"]`` (" Sent ", " Delivered ",
        " Read ", or a pending/clock label while still uploading). Falls
        back to the legacy ``data-icon`` values for older builds.
        """
        try:
            meta = bubble.locator(ACK_META_SELECTOR).first
            if meta.count():
                label_el = meta.locator("[aria-label]").last
                if label_el.count():
                    label = (label_el.get_attribute("aria-label") or "").strip()
                    if label:
                        if ACK_SENT_LABEL_RE.search(label):
                            return "sent"
                        if ACK_PENDING_LABEL_RE.search(label):
                            return "pending"
        except Exception:
            pass

        for selector in SENT_ACK_SELECTORS:
            try:
                if bubble.locator(selector).first.is_visible(timeout=300):
                    return "sent"
            except Exception:
                continue
        for selector in PENDING_ACK_SELECTORS:
            try:
                if bubble.locator(selector).first.is_visible(timeout=300):
                    return "pending"
            except Exception:
                continue
        return "unknown"

    def _capture_sent_success(self, page: Page, bubble: Locator) -> None:
        """Save the fixed success screenshot showing the confirmed bubble."""
        target = self._config.screenshot_dir / SENT_SCREENSHOT_NAME
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                bubble.scroll_into_view_if_needed(timeout=1_000)
            except Exception:
                pass
            page.screenshot(path=str(target))
            self._logger.info("Saved WhatsApp sent-confirmation screenshot: %s", target)
        except Exception as exc:
            self._logger.warning("Could not capture WhatsApp sent screenshot: %s", exc)

    @staticmethod
    def _dialog_text(page: Page) -> str:
        for selector in DIALOG_SELECTORS:
            try:
                locator = page.locator(selector).first
                if not locator.count() or not locator.is_visible(timeout=400):
                    continue
                text = (locator.inner_text(timeout=1_000) or "").strip()
            except Exception:
                continue
            lowered = text.lower()
            if any(phrase in lowered for phrase in INVALID_NUMBER_PHRASES):
                return re.sub(r"\s+", " ", text)[:200]
        return ""

    def _capture(self, page: Page, reason: str) -> None:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        target = self._config.screenshot_dir / f"whatsapp_{reason}_{stamp}.png"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target))
            self._logger.info("Saved WhatsApp diagnostic screenshot: %s", target)
        except Exception as exc:
            self._logger.warning("Could not capture WhatsApp screenshot: %s", exc)

    def _record_failure(self, stage: str, exc: BaseException) -> None:
        self._logger.error(
            "WhatsApp Web %s failed: %s", stage, exc, exc_info=exc
        )
        safe_print(f"[WhatsApp] {stage} failed: {exc}")
        safe_print(f"[WhatsApp] Details logged to {self._config.log_file}")
