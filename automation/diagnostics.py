"""Screenshot and simplified DOM capture for self-healing recovery."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

_SNAPSHOT_SCRIPT = """() => {
  const nodes = Array.from(document.querySelectorAll(
    'a, button, input, textarea, select, [role="button"], [role="menuitem"], [role="menu"], [aria-expanded], [class*="modal" i], [class*="popup" i]'
  ));
  return nodes.slice(0, 100).map((el) => {
    const style = window.getComputedStyle(el);
    const visible = style.display !== "none" && style.visibility !== "hidden" && el.offsetParent !== null;
    return {
      tag: el.tagName.toLowerCase(),
      id: el.id || "",
      name: el.getAttribute("name") || "",
      type: el.getAttribute("type") || "",
      role: el.getAttribute("role") || "",
      expanded: el.getAttribute("aria-expanded"),
      haspopup: el.getAttribute("aria-haspopup"),
      text: ((el.innerText || el.value || el.getAttribute("placeholder") || "").trim()).slice(0, 80),
      visible,
    };
  }).filter((item) => item.visible || item.expanded === "true");
}"""


@dataclass(frozen=True)
class PageSnapshot:
    """Lightweight diagnostic bundle sent to vision recovery."""

    screenshot: bytes
    dom: tuple[dict[str, Any], ...]
    url: str
    title: str
    screenshot_path: Path | None = None
    dom_path: Path | None = None

    def as_prompt_text(self, limit: int = 40) -> str:
        """Serialize a compact DOM excerpt for the vision prompt."""
        rows = []
        for item in self.dom[:limit]:
            rows.append(
                f"{item.get('tag')} id={item.get('id')} name={item.get('name')} "
                f"role={item.get('role')} expanded={item.get('expanded')} "
                f"text={item.get('text')!r}"
            )
        return "\n".join(rows)


class DiagnosticCapture:
    """Write screenshots and DOM snapshots under runtime/."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path("runtime")
        self._screenshots = self._root / "screenshots"
        self._dom = self._root / "dom"

    def capture(self, page: Page, name: str) -> PageSnapshot:
        """Capture viewport screenshot plus a simplified interactive DOM map."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
        screenshot_path = self._screenshots / f"{stamp}_{safe_name}.png"
        dom_path = self._dom / f"{stamp}_{safe_name}.json"

        screenshot = b""
        try:
            self._screenshots.mkdir(parents=True, exist_ok=True)
            screenshot = page.screenshot(type="png", full_page=False)
            screenshot_path.write_bytes(screenshot)
        except Exception:
            screenshot_path = None  # type: ignore[assignment]
            try:
                screenshot = page.screenshot(type="png", full_page=False)
            except Exception:
                screenshot = b""

        dom_items: tuple[dict[str, Any], ...] = ()
        try:
            raw = page.evaluate(_SNAPSHOT_SCRIPT)
            if isinstance(raw, list):
                dom_items = tuple(item for item in raw if isinstance(item, dict))
            self._dom.mkdir(parents=True, exist_ok=True)
            if dom_path:
                dom_path.write_text(json.dumps(list(dom_items), indent=2), encoding="utf-8")
        except Exception:
            dom_path = None  # type: ignore[assignment]

        url = ""
        title = ""
        try:
            url = page.url
            title = page.title()
        except Exception:
            pass

        return PageSnapshot(
            screenshot=screenshot,
            dom=dom_items,
            url=url,
            title=title,
            screenshot_path=screenshot_path if isinstance(screenshot_path, Path) else None,
            dom_path=dom_path if isinstance(dom_path, Path) else None,
        )
