"""Persistent, conservative recovery recipe memory."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class RecoveryMemory:
    """Store only validated successful proposals keyed by problem fingerprint."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def fingerprint(operation: str, url: str, error_type: str) -> str:
        raw = f"{operation}|{url}|{error_type}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def load(self, fingerprint: str) -> dict[str, Any] | None:
        data = self._read()
        value = data.get(fingerprint)
        return value if isinstance(value, dict) else None

    def save(self, fingerprint: str, proposal: dict[str, Any]) -> None:
        data = self._read()
        data[fingerprint] = proposal
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (OSError, ValueError):
            return {}


class VisualMemory:
    """SQLite cache of successful visual repairs keyed by the rendered screen."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS visual_memory (
                    screen_hash TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    action TEXT NOT NULL,
                    coordinates TEXT,
                    selector TEXT,
                    input_text TEXT,
                    diagnosis TEXT,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (screen_hash, goal)
                )"""
            )

    @staticmethod
    def screen_hash(screenshot: bytes) -> str:
        return hashlib.sha256(screenshot).hexdigest()

    def load(self, screenshot: bytes, goal: str) -> dict[str, Any] | None:
        if not screenshot:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """SELECT action, coordinates, selector, input_text, diagnosis, confidence
                   FROM visual_memory WHERE screen_hash = ? AND goal = ?""",
                (self.screen_hash(screenshot), goal),
            ).fetchone()
        if row is None:
            return None
        coordinates = json.loads(row[1]) if row[1] else None
        return {
            "visual_state_diagnosis": row[4] or "Previously successful visual repair.",
            "action": row[0], "selector": row[2], "target_coordinates": coordinates,
            "input_text": row[3], "confidence": row[5],
        }

    def save(self, screenshot: bytes, goal: str, solution: dict[str, Any]) -> None:
        if not screenshot:
            return
        coordinates = solution.get("target_coordinates")
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO visual_memory
                   (screen_hash, goal, action, coordinates, selector, input_text, diagnosis, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(screen_hash, goal) DO UPDATE SET
                   action=excluded.action, coordinates=excluded.coordinates,
                   selector=excluded.selector, input_text=excluded.input_text,
                   diagnosis=excluded.diagnosis, confidence=excluded.confidence""",
                (
                    self.screen_hash(screenshot), goal, solution["action"],
                    json.dumps(coordinates) if coordinates else None, solution.get("selector"),
                    solution.get("input_text"), solution.get("visual_state_diagnosis"),
                    solution["confidence"],
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)
