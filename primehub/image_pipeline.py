"""Type-aware local photo prep: square crop, protected EV, budgeted WebP."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFilter

from .webp import (
    DEFAULT_QUALITY,
    MAX_WIDTH,
    TARGET_BYTES,
    CompressedImage,
    compress_image_to_webp,
)

TYPE_A = "wholesale_box"
TYPE_B = "loose_or_shimmer"
TYPE_A_MARGIN = 0.08
TYPE_B_MARGIN = 0.0
TYPE_A_EV = 0.2
TYPE_B_EV = 0.15

_TYPE_A_HINTS = (
    "deal box",
    "dealbox",
    "dozenbox",
    "dozen box",
    "wholesale",
    "dalbox",
)


@dataclass(frozen=True)
class ProcessedImage:
    """Pipeline output ready for Cloudflare R2."""

    compressed: CompressedImage
    style: str
    margin: float
    ev: float
    original_width: int = 0
    original_height: int = 0

    @property
    def data(self) -> bytes:
        return self.compressed.data

    @property
    def filename(self) -> str:
        return self.compressed.filename


def classify_image_style(path: Path, folder: Path | None = None) -> str:
    """Type A when the folder is a deal/box SKU; otherwise loose/shimmer."""
    haystack = " ".join(
        part.replace("_", " ").replace("-", " ").lower()
        for part in (
            path.name,
            (folder or path.parent).name,
            str(folder or path.parent),
        )
    )
    if any(hint in haystack for hint in _TYPE_A_HINTS):
        return TYPE_A
    if " box" in f" {haystack} " or haystack.endswith(" box"):
        return TYPE_A
    return TYPE_B


def square_crop_with_margin(image: Image.Image, margin: float) -> Image.Image:
    """Center 1:1 crop, then keep ``margin`` of frame as breathing room."""
    rgb = image.convert("RGB")
    side = min(rgb.size)
    left = (rgb.width - side) // 2
    top = (rgb.height - side) // 2
    cropped = rgb.crop((left, top, left + side, top + side))
    inset = max(0.0, min(0.45, float(margin)))
    if inset <= 0:
        return cropped
    inner = max(1, int(round(side * (1.0 - 2.0 * inset))))
    content = cropped.resize((inner, inner), Image.Resampling.LANCZOS)
    backdrop = cropped.resize((side, side), Image.Resampling.LANCZOS)
    backdrop = backdrop.filter(ImageFilter.GaussianBlur(max(8, side // 40)))
    offset = (side - inner) // 2
    backdrop.paste(content, (offset, offset))
    return backdrop


def apply_protected_ev(image: Image.Image, ev: float) -> Image.Image:
    """Lift midtones by ``ev`` stops while rolling off highlights."""
    if abs(ev) < 1e-6:
        return image.convert("RGB")
    gain = 2.0 ** ev
    lut = [_protected_sample(index / 255.0, gain) for index in range(256)]
    return image.convert("RGB").point(lut * 3)


def _protected_sample(value: float, gain: float) -> int:
    # Less lift as the pixel approaches white so gold glitter does not clip.
    lift = 1.0 + (gain - 1.0) * ((1.0 - value) ** 1.2)
    out = value * lift
    if out > 0.92:
        out = 0.92 + (out - 0.92) * 0.35
    return int(max(0, min(255, round(out * 255.0))))


def process_product_image(
    image_path: Path,
    *,
    folder: Path | None = None,
    style: str | None = None,
) -> ProcessedImage:
    """Crop, tone, and export WebP under the storefront byte budget."""
    path = Path(image_path)
    chosen = style or classify_image_style(path, folder)
    margin = TYPE_A_MARGIN if chosen == TYPE_A else TYPE_B_MARGIN
    ev = TYPE_A_EV if chosen == TYPE_A else TYPE_B_EV
    if path.stem.lower() == "cover_all":
        margin = 0.0
        ev = 0.04
    original_bytes = path.stat().st_size if path.exists() else 0
    with Image.open(path) as opened:
        original_width, original_height = opened.size
        framed = square_crop_with_margin(opened, margin)
        toned = apply_protected_ev(framed, ev)
        compressed = compress_image_to_webp(
            toned,
            path,
            original_bytes=original_bytes,
            max_width=MAX_WIDTH,
            quality=DEFAULT_QUALITY,
            target_bytes=TARGET_BYTES,
        )
    return ProcessedImage(
        compressed=compressed,
        style=chosen,
        margin=margin,
        ev=ev,
        original_width=original_width,
        original_height=original_height,
    )
