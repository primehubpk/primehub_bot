"""JSON visual-memory store for learned recovery rules.

The file lives at ``runtime/memory/agent_memory.json`` so a later run can
replay a previously successful selector/action without calling vision again.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def normalize_goal(goal: str) -> str:
    """Collapse whitespace so the same intent always hashes to one key."""
    return " ".join((goal or "").strip().lower().split())


class AgentMemory:
    """Learned selector/action rules keyed by goal + optional URL fragment."""

    def __init__(self, path: Path | str = Path("runtime/memory/agent_memory.json")) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def lookup(self, goal: str, url: str = "") -> dict[str, Any] | None:
        """Return the best matching learned rule, or None if unknown."""
        key = normalize_goal(goal)
        if not key:
            return None
        haystack = (url or "").lower()
        matches: list[dict[str, Any]] = []
        for rule in self._rules():
            if normalize_goal(str(rule.get("goal", ""))) != key:
                continue
            fragment = str(rule.get("url_contains") or "").lower()
            if fragment and fragment not in haystack:
                continue
            matches.append(rule)
        if not matches:
            return None
        matches.sort(
            key=lambda rule: (int(rule.get("hits") or 0), str(rule.get("learned_at") or "")),
            reverse=True,
        )
        return dict(matches[0])

    def save(
        self,
        goal: str,
        url: str,
        action: str,
        selector: str | None,
        input_text: str | None = None,
        diagnosis: str = "",
        confidence: float = 0.0,
    ) -> dict[str, Any]:
        """Persist a newly verified recovery rule."""
        key = normalize_goal(goal)
        fragment = self._url_fragment(url)
        payload = {
            "goal": key,
            "url_contains": fragment,
            "action": action,
            "selector": selector,
            "input_text": input_text,
            "diagnosis": diagnosis,
            "confidence": confidence,
            "hits": 1,
            "learned_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            data = self._read()
            rules = list(data.get("rules") or [])
            replaced = False
            for index, rule in enumerate(rules):
                if (
                    normalize_goal(str(rule.get("goal", ""))) == key
                    and str(rule.get("url_contains") or "") == fragment
                    and str(rule.get("action") or "") == action
                    and str(rule.get("selector") or "") == str(selector or "")
                ):
                    payload["hits"] = int(rule.get("hits") or 0) + 1
                    rules[index] = payload
                    replaced = True
                    break
            if not replaced:
                rules.append(payload)
            data["version"] = 1
            data["rules"] = rules
            self._write(data)
        return payload

    def record_hit(self, rule: dict[str, Any]) -> None:
        """Bump the hit counter after a cached rule recovered the page."""
        self.save(
            goal=str(rule.get("goal") or ""),
            url=str(rule.get("url_contains") or ""),
            action=str(rule.get("action") or "click"),
            selector=rule.get("selector"),
            input_text=rule.get("input_text"),
            diagnosis=str(rule.get("diagnosis") or ""),
            confidence=float(rule.get("confidence") or 0.0),
        )

    def _rules(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._read()
        raw = data.get("rules") or []
        return [item for item in raw if isinstance(item, dict)]

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": 1, "rules": []}
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {"version": 1, "rules": []}
        return parsed if isinstance(parsed, dict) else {"version": 1, "rules": []}

    def _write(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=self._path.parent,
            text=True,
        )
        os.close(handle)
        try:
            Path(temp_name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp_name, self._path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _url_fragment(url: str) -> str:
        text = (url or "").strip()
        if not text:
            return ""
        # Persist a short, stable fragment (path tail) so the same popup on
        # the tracking page matches later even if query strings change.
        without_query = text.split("?", 1)[0]
        parts = [part for part in without_query.split("/") if part]
        return parts[-1][:80] if parts else without_query[-80:]
