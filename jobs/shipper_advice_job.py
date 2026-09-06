"""Standalone Shipper Advice synchronization job."""
from __future__ import annotations

from datetime import datetime

from rehan_bot.automation.shipper_advice import (
    ShipperAdviceAction,
    ShipperAdvicePage,
    ShipperAdviceResult,
)


class ShipperAdviceJob:
    """Coordinate validated advice submissions and return audit results."""

    def __init__(self, portal: ShipperAdvicePage) -> None:
        self._portal = portal

    def run_pending(self, instruction: str) -> tuple[ShipperAdviceResult, ...]:
        """Discover pending CNs and submit the configured instruction for each."""
        pending = self._portal.find_pending()
        actions = tuple(
            ShipperAdviceAction(tracking_number=number, advice_text=instruction)
            for number in pending
        )
        return self.run(actions)

    def run(self, actions: tuple[ShipperAdviceAction, ...]) -> tuple[ShipperAdviceResult, ...]:
        """Submit actions and retain only verified outcomes."""
        results: list[ShipperAdviceResult] = []
        for action in actions:
            self._portal.submit(action)
            verified = self._portal.verify_submission(action)
            results.append(
                ShipperAdviceResult(
                    tracking_number=action.tracking_number,
                    submitted=verified,
                    submitted_at=datetime.now() if verified else None,
                )
            )
        return tuple(results)
