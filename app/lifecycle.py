"""Process lifecycle and graceful shutdown supervisor."""
from __future__ import annotations
import signal
import threading
from types import FrameType
from collections.abc import Callable

class Lifecycle:
    def __init__(self, shutdown_callbacks: tuple[Callable[[], object], ...]) -> None:
        self._callbacks = shutdown_callbacks
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._stopped = False

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        del signum, frame
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
        self._stop_event.set()
        for callback in self._callbacks:
            try:
                callback()
            except Exception:
                continue

    def wait(self) -> None:
        self._stop_event.wait()

    def stop(self) -> None:
        self._handle_signal(0, None)

    def shutdown_quietly(self) -> None:
        """Close every registered resource exactly once, never raising."""
        self.stop()
