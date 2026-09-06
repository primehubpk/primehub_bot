"""Structured JSON logging with rotating file support."""
from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    """Serialize log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_file_logger(
    name: str,
    log_file: Path,
    level: int = logging.INFO,
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
    propagate: bool = False,
) -> logging.Logger:
    """Attach one rotating JSON file handler to the named logger."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = propagate

    target = os.path.abspath(str(log_file))
    for handler in logger.handlers:
        if os.path.abspath(getattr(handler, "baseFilename", "")) == target:
            return logger

    handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    return logger


def configure_logging(
    log_file: Path,
    level: int = logging.INFO,
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure the root application logger."""
    return configure_file_logger(
        "rehan_bot",
        log_file,
        level=level,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )
