"""Safe Playwright storage-state persistence."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext

class SessionManager:
    """Persist storage state atomically and recover from corruption."""

    def __init__(self, session_file: Path) -> None:
        self._session_file = session_file

    @property
    def path(self) -> Path:
        """Return the session file path."""
        return self._session_file

    @property
    def exists(self) -> bool:
        """Whether the session artifact exists."""
        return self._session_file.is_file()

    def is_valid_file(self) -> bool:
        """Return whether the session file is valid JSON storage state."""
        if not self.exists:
            return False
        try:
            payload = json.loads(self._session_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return isinstance(payload, dict) and isinstance(payload.get("cookies", []), list)

    def remove_corrupt(self) -> None:
        """Remove a corrupt session file if present."""
        try:
            self._session_file.unlink(missing_ok=True)
        except OSError:
            pass

    def save(self, context: BrowserContext) -> None:
        """Atomically persist Playwright storage state."""
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self._session_file.name}.",
            suffix=".tmp",
            dir=self._session_file.parent,
            text=True,
        )
        os.close(fd)
        try:
            context.storage_state(path=temp_name)
            os.replace(temp_name, self._session_file)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def load_payload(self) -> dict[str, Any] | None:
        """Load validated storage state when available."""
        if not self.is_valid_file():
            return None
        try:
            payload = json.loads(self._session_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None
