"""Self-healing fallback: JSON memory first, then AI vision.

When a selector gets stuck or an unexpected popup appears:

1. Look up ``runtime/memory/agent_memory.json`` for a previously learned
   selector/action for this goal + page.
2. If unknown, capture ``runtime/screenshots/blocker_<timestamp>.png`` and
   ask the configured vision chain (OpenAI / Gemini / …) what to click.
3. Apply the action, verify the page recovered, and persist the rule.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from rehan_bot.ai.recovery import RecoveryRejected, SafeRecoveryExecutor
from rehan_bot.ai.schemas import VisualSolution
from rehan_bot.ai.vision import VisionPreprocessor, VisionPromptBuilder
from rehan_bot.automation.agent_memory import AgentMemory
from rehan_bot.automation.diagnostics import DiagnosticCapture

logger = logging.getLogger("rehan_bot.automation.self_heal")


class SelfHealingAgent:
    """RecoveryProtocol implementation with visual memory + vision fallback."""

    def __init__(
        self,
        memory: AgentMemory | None = None,
        provider: Any | None = None,
        executor: SafeRecoveryExecutor | None = None,
        diagnostics: DiagnosticCapture | None = None,
        screenshot_dir: Path | None = None,
    ) -> None:
        self._memory = memory or AgentMemory()
        self._provider = provider
        self._executor = executor or SafeRecoveryExecutor()
        self._diagnostics = diagnostics or DiagnosticCapture()
        self._preprocessor = VisionPreprocessor()
        self._prompt_builder = VisionPromptBuilder()
        self._screenshot_dir = Path(screenshot_dir or "runtime/screenshots")

    @property
    def memory(self) -> AgentMemory:
        return self._memory

    def recover(self, page: Page, operation: str, error: Exception) -> bool:
        """RecoveryProtocol compatibility shim."""
        del error
        return self.heal(page, operation)

    def repair(self, page: Page, goal: str) -> bool:
        """Same entry point ``ResilientActions`` already calls."""
        return self.heal(page, goal)

    def heal(self, page: Page, goal: str) -> bool:
        """Memory-first recovery; vision only when the situation is unknown."""
        url = self._page_url(page)

        cached = self._memory.lookup(goal, url)
        if cached is not None:
            if self._apply_rule(page, cached):
                self._memory.record_hit(cached)
                logger.info("Recovered %r from agent_memory.json", goal)
                return True
            logger.info("Cached rule for %r no longer applies; asking vision", goal)

        blocker = self._capture_blocker(page)
        if blocker is not None:
            logger.info("Captured blocker screenshot: %s", blocker)

        if self._provider is None:
            return False

        snapshot = self._diagnostics.capture(page, "self_heal")
        image_bytes = snapshot.screenshot
        if not image_bytes and blocker is not None:
            try:
                image_bytes = blocker.read_bytes()
            except OSError:
                image_bytes = b""
        if not image_bytes:
            return False

        try:
            prompt = self._prompt_builder.build(goal, url, snapshot.as_prompt_text())
            solution = self._provider.propose(
                self._preprocessor.prepare(image_bytes), prompt
            )
        except Exception as exc:
            logger.warning("Vision helper failed for %r: %s", goal, exc)
            return False

        if not self._apply_solution(page, solution):
            return False

        if solution.selector:
            self._memory.save(
                goal=goal,
                url=url,
                action=solution.action,
                selector=solution.selector,
                input_text=solution.input_text,
                diagnosis=solution.visual_state_diagnosis,
                confidence=solution.confidence,
            )
            logger.info(
                "Learned recovery rule for %r -> %s %s",
                goal,
                solution.action,
                solution.selector,
            )
        return True

    def _apply_rule(self, page: Page, rule: dict[str, Any]) -> bool:
        action = str(rule.get("action") or "click")
        if action == "dismiss":
            action = "dismiss_popup"
        if action == "fill":
            action = "type"
        try:
            solution = VisualSolution.model_validate(
                {
                    "visual_state_diagnosis": rule.get("diagnosis")
                    or "Cached recovery rule",
                    "action": action,
                    "selector": rule.get("selector"),
                    "target_coordinates": None,
                    "input_text": rule.get("input_text"),
                    "confidence": float(rule.get("confidence") or 0.9),
                }
            )
        except Exception:
            return False
        return self._apply_solution(page, solution)

    def _apply_solution(self, page: Page, solution: VisualSolution) -> bool:
        try:
            self._executor.execute(page, solution)
        except (RecoveryRejected, Exception):
            return False
        try:
            page.wait_for_timeout(400)
        except Exception:
            pass
        return True

    def _capture_blocker(self, page: Page) -> Path | None:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        target = self._screenshot_dir / f"blocker_{stamp}.png"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target), type="png", full_page=False)
            return target
        except Exception as exc:
            logger.warning("Could not capture blocker screenshot: %s", exc)
            return None

    @staticmethod
    def _page_url(page: Page) -> str:
        try:
            return page.url or ""
        except Exception:
            return ""
