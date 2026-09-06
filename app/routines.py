"""Production routine orchestration for Rehan Bot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rehan_bot.automation.payments import PaymentStatementParser
from rehan_bot.automation.tracking import MPortalTrackingPage
from rehan_bot.config import Settings
from rehan_bot.jobs.reconciliation_job import ReconciliationJob
from rehan_bot.jobs.tracking_job import TrackingJob
from rehan_bot.notifications.service import (
    Notification,
    NotificationService,
)
from rehan_bot.notifications.whatsapp import build_tracking_notifier
from rehan_bot.persistence.repositories.parcel_repo import (
    ParcelRepository,
)
from rehan_bot.persistence.repositories.payment_repo import (
    PaymentRepository,
)
from rehan_bot.portal.client import PortalClient
from rehan_bot.reporting.service import DailyReportService


class RoutineRunner:
    """Bridge CLI and scheduler calls to workflow services."""

    def __init__(
        self,
        portal: PortalClient,
        sessions: Any,
        report: DailyReportService,
        notifications: NotificationService,
        settings: Settings,
        tracking_numbers: tuple[str, ...] = (),
        payment_statement: str = "",
        ai_recovery: Any | None = None,
    ) -> None:
        self._portal = portal
        self._sessions = sessions
        self._report = report
        self._notifications = notifications
        self._settings = settings
        self._tracking_numbers = tracking_numbers
        self._payment_statement = payment_statement
        self._ai_recovery = ai_recovery

    def _dismiss_popup(self) -> None:
        """Dismiss announcement or scam alert popup if present."""
        page = self._portal.page
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass

        try:
            close_elem = page.locator('text="Close"').first
            if close_elem.is_visible(timeout=1000):
                close_elem.click(force=True)
                page.wait_for_timeout(500)
        except Exception:
            pass

    def _ensure_tracking_page(self) -> None:
        """Ensure modal is closed and navigate to Tracking sub-item from sidebar."""
        self._dismiss_popup()

        if not self._settings.mp_tracking_url:
            page = self._portal.page
            try:
                # 1. Pehle Main Menu 'Tracking' par click karein taake dropdown khulay
                main_tracking = page.locator('nav, .sidebar, div').locator('text="Tracking"').first
                if main_tracking.is_visible(timeout=2000):
                    main_tracking.click(force=True)
                    page.wait_for_timeout(500)

                # 2. Phir Sub-menu mein jo 'Tracking' hai us par click karein
                sub_tracking = page.locator('text="Tracking"').nth(1)
                if sub_tracking.is_visible(timeout=1500):
                    sub_tracking.click(force=True)
                    page.wait_for_timeout(1000)
                else:
                    # Agar nth(1) na miley to link se try karein
                    page.locator('a:has-text("Tracking")').last.click(force=True)
                    page.wait_for_timeout(1000)
            except Exception:
                pass

    def _login(self) -> None:
        """Start the browser and authenticate with M&P."""

        self._portal.start()

        result = self._portal.login()

        if result.state.value != "authenticated":
            raise RuntimeError(
                "M&P portal is not authenticated: "
                f"{result.state.value}"
            )

    def track(
        self,
        tracking_numbers: tuple[str, ...],
    ) -> int:
        """
        Run deterministic M&P tracking.

        CLI supplied tracking numbers are passed directly into the
        TrackingJob. No tracking/session state is duplicated here.
        """

        if not tracking_numbers:
            raise ValueError(
                "No tracking number supplied. "
                "Use: python main.py track 123456789"
            )

        self._login()

        session = self._sessions()

        try:
            tracking_page = MPortalTrackingPage(
                self._portal.page,
                self._settings.mp_tracking_url,
                recovery=self._ai_recovery,
                relogin=self._portal.login,
                action_timeout_ms=self._settings.action_timeout_ms,
                recovery_max_retries=self._settings.recovery_max_retries,
                loader_timeout_ms=self._settings.tracking_loader_timeout_ms,
                result_timeout_ms=self._settings.tracking_result_timeout_ms,
            )

            repository = ParcelRepository(session)

            job = TrackingJob(
                portal=tracking_page,
                repository=repository,
                notifier=build_tracking_notifier(self._settings),
            )

            result = job.run(tracking_numbers)

            if isinstance(result, int):
                return result

            if result is None:
                return len(tracking_numbers)

            try:
                return int(result)
            except (TypeError, ValueError):
                return len(tracking_numbers)

        finally:
            session.close()

    def send_daily_report(self) -> bool:
        """Build today's parcel summary and send it over WhatsApp."""
        if self._report is None:
            return False
        return bool(self._report.send_whatsapp())

    def close_browsers(self) -> None:
        """Close the M&P portal Playwright context without raising."""
        if self._portal is None:
            return
        try:
            self._portal.close()
        except Exception:
            pass

    def morning(self) -> None:
        """11:00 PKT: track configured parcels, then send the daily report."""

        try:
            if self._tracking_numbers:
                self.track(self._tracking_numbers)
            self.send_daily_report()
        finally:
            self.close_browsers()

    def periodic(self) -> None:
        """Run periodic tracking and shipper-advice notification."""

        if self._tracking_numbers:
            self.track(
                self._tracking_numbers
            )

        try:
            self._notifications.send(
                Notification(
                    event="SHIPPER_ADVICE_CHECK",
                    title="Shipper Advice Check",
                    message=(
                        "Pending shipper advice check "
                        "completed."
                    ),
                    severity="info",
                )
            )
        except Exception:
            pass

    def evening(self) -> None:
        """Run COD reconciliation followed by daily reporting."""

        if self._payment_statement:
            self._login()

            session = self._sessions()

            try:
                statement_path = Path(
                    self._payment_statement
                )

                if not statement_path.exists():
                    raise FileNotFoundError(
                        "COD statement file does not exist: "
                        f"{statement_path}"
                    )

                statement_text = (
                    statement_path.read_text(
                        encoding="utf-8"
                    )
                )

                transactions = (
                    PaymentStatementParser()
                    .parse_csv(statement_text)
                )

                repository = PaymentRepository(
                    session
                )

                ReconciliationJob(
                    repository
                ).run(transactions)

            finally:
                session.close()

        try:
            self.send_daily_report()
        finally:
            self.close_browsers()
