"""Human-paced sequential delays and live console progress."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from rehan_bot.config import Settings


def folder_label(folder: Path) -> str:
    path = Path(folder)
    parent = path.parent.name.strip()
    if parent:
        return f"{parent} / {path.name}"
    return path.name


def emit(message: str) -> None:
    print(message, flush=True)
    sys.stderr.flush()


def pause(seconds: float) -> None:
    delay = max(0.0, float(seconds or 0))
    if delay:
        time.sleep(delay)


def image_delay_seconds(settings: Settings) -> float:
    return max(0.0, float(getattr(settings, "primehub_image_delay_seconds", 1.5) or 0))


def folder_delay_seconds(settings: Settings, *, dry_run: bool = False) -> float:
    if dry_run:
        return 0.0
    return max(0.0, float(getattr(settings, "primehub_folder_delay_seconds", 2.5) or 0))
