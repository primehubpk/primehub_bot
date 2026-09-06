"""Strict schemas for AI-assisted UI recovery."""
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RecoveryAction(str, Enum):
    """Actions the AI is permitted to propose."""

    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    WAIT = "wait"
    DISMISS = "dismiss"


class TargetKind(str, Enum):
    """Supported target identification methods."""

    CSS = "css"
    TEXT = "text"
    ROLE = "role"
    COORDINATE = "coordinate"


class BoundingBox(BaseModel):
    """Normalized screenshot bounding box."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class RecoveryTarget(BaseModel):
    """Constrained target description returned by a vision model."""

    model_config = ConfigDict(extra="forbid")

    kind: TargetKind
    value: str = Field(min_length=1, max_length=500)
    bounding_box: BoundingBox | None = None


class RecoveryProposal(BaseModel):
    """Validated AI proposal; execution requires a separate policy gate."""

    model_config = ConfigDict(extra="forbid")

    action: RecoveryAction
    target: RecoveryTarget
    value: str | None = Field(default=None, max_length=2_000)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=2_000)
    prerequisite: str | None = Field(default=None, max_length=200)
    expected_url_contains: str | None = Field(default=None, max_length=500)


class TargetCoordinates(BaseModel):
    """Viewport coordinates returned by a visual solver."""

    model_config = ConfigDict(extra="forbid")
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class VisualSolution(BaseModel):
    """The public, provider-neutral strict JSON contract for visual repair."""

    model_config = ConfigDict(extra="forbid")

    visual_state_diagnosis: str = Field(min_length=1, max_length=2_000)
    action: Literal["click", "type", "select", "wait", "dismiss_popup"]
    selector: str | None = Field(default=None, max_length=500)
    target_coordinates: TargetCoordinates | None = None
    input_text: str | None = Field(default=None, max_length=2_000)
    confidence: float = Field(ge=0.0, le=1.0)
