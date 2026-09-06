"""Screenshot preparation and deterministic vision prompts."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class VisionImage:
    mime_type: str
    data: bytes

    @property
    def base64_data(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


class VisionPreprocessor:
    def __init__(self, max_dimension: int = 1600, quality: int = 82) -> None:
        self._max_dimension = max_dimension
        self._quality = quality

    def prepare(self, image_bytes: bytes) -> VisionImage:
        if not image_bytes:
            raise ValueError("Screenshot bytes cannot be empty")
        with Image.open(io.BytesIO(image_bytes)) as image:
            image = image.convert("RGB")
            image.thumbnail((self._max_dimension, self._max_dimension))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=self._quality, optimize=True)
            return VisionImage("image/jpeg", output.getvalue())


class VisionPromptBuilder:
    def build(
        self,
        goal_description: str,
        current_url: str = "",
        dom_snapshot: str = "",
    ) -> str:
        dom = dom_snapshot.strip() or "(DOM snapshot unavailable)"
        return (
            "Analyze the supplied browser viewport screenshot and interactive DOM. "
            "Return exactly one JSON object and no markdown. The required schema is: "
            '{"visual_state_diagnosis":"what is visibly happening",'
            '"action":"click|type|select|wait|dismiss_popup",'
            '"selector":"optional CSS or XPath",'
            '"target_coordinates":{"x":int,"y":int},'
            '"input_text":"only for type/select", "confidence":0.0}. '
            "Use one action only. Give a selector when it is stable; otherwise use viewport "
            "coordinates for a click. Never return scripts, credentials, or hidden-page actions. "
            "If a dropdown is expanded, click its visible child rather than toggling its parent. "
            "Use dismiss_popup for blocking modals or overlays.\n"
            f"Goal: {goal_description}\nCurrent URL: {current_url}\n"
            f"Interactive DOM snapshot:\n{dom}"
        )
