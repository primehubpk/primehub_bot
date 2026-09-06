"""Application dependency-injection container."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from rehan_bot.ai.provider import VisionFallbackChain, build_vision_fallback_chain
from rehan_bot.ai.recovery import AIRecoveryService
from rehan_bot.automation.agent_memory import AgentMemory
from rehan_bot.automation.self_heal import SelfHealingAgent
from rehan_bot.config import Settings
from rehan_bot.notifications.service import NotificationService
from rehan_bot.notifications.whatsapp import (
    build_notifier as build_whatsapp_notifier,
    build_web_sender,
)
from rehan_bot.observability.logging import configure_logging
from rehan_bot.persistence.database import Base, create_engine_for_url, create_session_factory
from rehan_bot.portal.client import PortalClient
from rehan_bot.reporting.service import DailyReportService
from rehan_bot.scheduler.scheduler import RoutineScheduler, ScheduleConfig


@dataclass
class AppContainer:
    settings: Settings
    engine: Engine
    sessions: sessionmaker[Session]
    notifications: NotificationService
    scheduler: RoutineScheduler
    portal: PortalClient
    report: DailyReportService
    ai_providers: VisionFallbackChain | None
    ai_recovery: SelfHealingAgent | AIRecoveryService | None

    def close(self) -> None:
        """Close browsers, scheduler, and DB connections without raising."""
        for closer in (
            self.scheduler.shutdown,
            self.portal.close,
            self.report.close,
            self.engine.dispose,
        ):
            try:
                closer()
            except Exception:
                continue


def _default_notifications(settings: Settings) -> NotificationService:
    """Wire the configured WhatsApp channel into the dispatcher."""
    whatsapp = build_whatsapp_notifier(settings)
    return NotificationService((whatsapp,) if whatsapp is not None else ())


def build_container(settings: Settings, notification_service: NotificationService | None = None) -> AppContainer:
    configure_logging(Path(settings.log_file))

    engine = create_engine_for_url(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    notifications = notification_service or _default_notifications(settings)
    scheduler = RoutineScheduler(ScheduleConfig(
        timezone=settings.scheduler_timezone,
        hourly_minutes=settings.scheduler_interval_minutes,
        morning_hour=settings.morning_report_hour,
        morning_minute=settings.morning_report_minute,
        evening_hour=settings.evening_report_hour,
        evening_minute=settings.evening_report_minute,
    ))
    whatsapp_sender = build_web_sender(settings)
    report = DailyReportService(
        sessions(), notifications, whatsapp_sender=whatsapp_sender
    )

    ai_providers: VisionFallbackChain | None = None
    try:
        ai_providers = build_vision_fallback_chain(settings)
    except RuntimeError:
        # Deterministic workflows remain usable when AI is intentionally disabled.
        pass

    # Memory-first self-healer: replay a learned selector from
    # agent_memory.json, otherwise capture a blocker screenshot and ask vision.
    ai_recovery = SelfHealingAgent(
        memory=AgentMemory(settings.agent_memory_path),
        provider=ai_providers,
        screenshot_dir=Path("runtime/screenshots"),
    )

    portal = PortalClient(settings, Path(settings.session_file), recovery=ai_recovery)

    return AppContainer(
        settings=settings,
        engine=engine,
        sessions=sessions,
        notifications=notifications,
        scheduler=scheduler,
        portal=portal,
        report=report,
        ai_providers=ai_providers,
        ai_recovery=ai_recovery,
    )
