"""Small dependency-free production periodic scheduler."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Event, Lock, Thread, current_thread
from zoneinfo import ZoneInfo

@dataclass(frozen=True)
class ScheduleConfig:
    timezone: str = 'Asia/Karachi'
    hourly_minutes: int = 60
    morning_hour: int = 11
    morning_minute: int = 0
    evening_hour: int = 20
    evening_minute: int = 0

@dataclass(frozen=True)
class ScheduledRoutine:
    routine_id: str
    callback: Callable[[], object]
    kind: str

class RoutineScheduler:
    """Run morning, periodic, and evening routines safely."""
    def __init__(self, config: ScheduleConfig) -> None:
        if config.hourly_minutes < 1:
            raise ValueError('hourly_minutes must be >= 1')
        self._config=config; self._routines={}; self._stop=Event(); self._lock=Lock(); self._thread=None; self._running=False

    def add_routines(self, morning: Callable[[], object], periodic: Callable[[], object], evening: Callable[[], object]) -> None:
        self._routines={
            'morning_routine': ScheduledRoutine('morning_routine',morning,'morning'),
            'periodic_routine': ScheduledRoutine('periodic_routine',periodic,'periodic'),
            'evening_routine': ScheduledRoutine('evening_routine',evening,'evening'),
        }

    def start(self) -> None:
        with self._lock:
            if self._running: return
            self._stop.clear(); self._running=True
            self._thread=Thread(target=self._run,name='rehan-bot-scheduler',daemon=True); self._thread.start()

    def _run(self) -> None:
        tz=ZoneInfo(self._config.timezone); next_periodic=datetime.now(tz)+timedelta(minutes=self._config.hourly_minutes); morning_fired=None; evening_fired=None
        while not self._stop.is_set():
            now=datetime.now(tz)
            if now>=next_periodic:
                self._safe_call(self._routines.get('periodic_routine')); next_periodic=now+timedelta(minutes=self._config.hourly_minutes)
            if now.hour==self._config.morning_hour and now.minute==self._config.morning_minute and morning_fired!=now.date():
                self._safe_call(self._routines.get('morning_routine')); morning_fired=now.date()
            if now.hour==self._config.evening_hour and now.minute==self._config.evening_minute and evening_fired!=now.date():
                self._safe_call(self._routines.get('evening_routine')); evening_fired=now.date()
            self._stop.wait(1.0)
        with self._lock: self._running=False

    @staticmethod
    def _safe_call(routine: ScheduledRoutine|None) -> None:
        if routine is None: return
        try: routine.callback()
        except Exception: return

    def shutdown(self) -> None:
        self._stop.set(); thread=self._thread
        if thread is not None and thread is not current_thread(): thread.join(timeout=10)
        with self._lock: self._running=False

    @property
    def running(self)->bool: return self._running
    @property
    def routine_ids(self)->frozenset[str]: return frozenset(self._routines)
