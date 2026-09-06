"""Visual self-healing service: screenshot, solve, execute, remember."""
from __future__ import annotations

from dataclasses import dataclass

from playwright.sync_api import Page

from rehan_bot.ai.fallback import VisionFallbackChain
from rehan_bot.ai.memory import VisualMemory
from rehan_bot.ai.schemas import RecoveryProposal, TargetKind, VisualSolution
from rehan_bot.ai.vision import VisionPreprocessor, VisionPromptBuilder
from rehan_bot.automation.diagnostics import DiagnosticCapture
from rehan_bot.portal.selectors import PortalSelectors


class RecoveryRejected(Exception):
    """A vision proposal did not meet the browser safety policy."""


@dataclass(frozen=True)
class RecoveryPolicy:
    minimum_confidence: float = 0.65
    maximum_actions: int = 3


class SafeRecoveryExecutor:
    """Execute only one bounded, visible, viewport-safe visual action."""

    def __init__(self, policy: RecoveryPolicy | None = None) -> None:
        self._policy = policy or RecoveryPolicy()

    def validate(self, solution: VisualSolution | RecoveryProposal) -> None:
        # Preserve the pre-existing internal proposal API while providers use
        # the stricter VisualSolution contract.
        if isinstance(solution, RecoveryProposal):
            if solution.confidence < self._policy.minimum_confidence:
                raise RecoveryRejected("Vision confidence is below the execution threshold")
            if solution.target.kind is TargetKind.COORDINATE:
                raise RecoveryRejected("Legacy coordinate proposals are not accepted")
            return
        if solution.confidence < self._policy.minimum_confidence:
            raise RecoveryRejected("Vision confidence is below the execution threshold")
        if solution.action in {"click", "type", "select"} and not (solution.selector or solution.target_coordinates):
            raise RecoveryRejected("Interactive solution requires selector or coordinates")
        if solution.target_coordinates and solution.action != "click":
            raise RecoveryRejected("Coordinates are allowed only for click")
        if solution.action in {"type", "select"} and solution.input_text is None:
            raise RecoveryRejected("Type/select action requires input_text")

    def execute(self, page: Page, solution: VisualSolution) -> None:
        self.validate(solution)
        if solution.action == "wait":
            page.wait_for_timeout(1_000)
            return
        if solution.action == "dismiss_popup":
            self._dismiss(page)
            return
        if solution.target_coordinates:
            viewport = page.viewport_size or {"width": 1440, "height": 900}
            x, y = solution.target_coordinates.x, solution.target_coordinates.y
            if not (0 <= x <= viewport["width"] and 0 <= y <= viewport["height"]):
                raise RecoveryRejected("Coordinate target is outside the viewport")
            page.mouse.click(x, y)
            return
        assert solution.selector
        locator = page.locator(solution.selector).first
        if locator.count() < 1 or not locator.is_visible():
            raise RecoveryRejected("Vision selector is not visible")
        if solution.action == "click":
            locator.click(timeout=3_000, force=True)
        elif solution.action == "type":
            locator.fill(solution.input_text or "", timeout=3_000)
        else:
            locator.select_option(solution.input_text or "", timeout=3_000)

    @staticmethod
    def _dismiss(page: Page) -> None:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        for selector in PortalSelectors.OVERLAY_CLOSE.candidates:
            try:
                locator = page.locator(selector).first
                if locator.count() and locator.is_visible():
                    locator.click(timeout=1_000, force=True)
                    return
            except Exception:
                continue


class AIRecoveryService:
    """Provider cascade and persistent visual solution memory."""

    def __init__(self, provider: VisionFallbackChain, executor: SafeRecoveryExecutor | None = None,
                 memory: VisualMemory | None = None, diagnostics: DiagnosticCapture | None = None) -> None:
        self._provider = provider
        self._executor = executor or SafeRecoveryExecutor()
        self._memory = memory
        self._preprocessor = VisionPreprocessor()
        self._prompt_builder = VisionPromptBuilder()
        self._diagnostics = diagnostics or DiagnosticCapture()

    def repair(self, page: Page, goal: str) -> bool:
        """Try up to three visual repair iterations. Successful repairs are cached."""
        for iteration in range(self._executor._policy.maximum_actions):
            snapshot = self._diagnostics.capture(page, f"visual_repair_{iteration + 1}")
            if not snapshot.screenshot:
                return False
            solution: VisualSolution | None = None
            if self._memory:
                cached = self._memory.load(snapshot.screenshot, goal)
                if cached:
                    try:
                        solution = VisualSolution.model_validate(cached)
                    except ValueError:
                        solution = None
            if solution is None:
                try:
                    prompt = self._prompt_builder.build(goal, snapshot.url, snapshot.as_prompt_text())
                    solution = self._provider.propose(self._preprocessor.prepare(snapshot.screenshot), prompt)
                except Exception:
                    # The fallback chain has already tried every configured
                    # provider. Repeating it blindly causes long UI stalls.
                    return False
            try:
                self._executor.execute(page, solution)
                page.wait_for_timeout(500)
                if self._memory:
                    self._memory.save(snapshot.screenshot, goal, solution.model_dump(mode="json"))
                return True
            except Exception:
                continue
        return False

    def recover(self, page: Page, operation: str, error: Exception) -> bool:
        """Compatibility protocol used by existing resilient workflows."""
        return self.repair(page, f"{operation}; failure={type(error).__name__}")
