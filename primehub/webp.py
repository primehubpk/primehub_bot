"""Local WebP compression so storefront images stay small and fast."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

WEBP_CACHE_VARIANT = "r2-webp-v1-w800-q80-100k"
MAX_WIDTH = 800
DEFAULT_QUALITY = 80
TARGET_BYTES = 100 * 1024
MIN_QUALITY = 32
MIN_WIDTH = 480


@dataclass(frozen=True)
class CompressedImage:
    """Optimized WebP bytes plus the knobs that produced them."""

    data: bytes
    width: int
    height: int
    quality: int
    original_bytes: int
    original_path: Path

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def filename(self) -> str:
        return f"{self.original_path.stem}.webp"

    def summary(self) -> dict[str, int | str]:
        return {
            "format": "webp",
            "width": self.width,
            "height": self.height,
            "quality": self.quality,
            "bytes": self.size_bytes,
            "original_bytes": self.original_bytes,
        }


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return image.convert("RGB")


def _fit_width(image: Image.Image, max_width: int) -> Image.Image:
    if image.width <= max_width:
        return image
    ratio = max_width / float(image.width)
    height = max(1, int(image.height * ratio))
    return image.resize((max_width, height), Image.Resampling.LANCZOS)


def _encode_webp(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(
        buffer,
        format="WEBP",
        quality=max(1, min(100, quality)),
        method=6,
    )
    return buffer.getvalue()


def compress_image_to_webp(
    image: Image.Image,
    original_path: Path,
    *,
    original_bytes: int = 0,
    max_width: int = MAX_WIDTH,
    quality: int = DEFAULT_QUALITY,
    target_bytes: int = TARGET_BYTES,
) -> CompressedImage:
    """Encode an already-opened RGB image to budgeted WebP."""
    rgb = _to_rgb(image)
    path = Path(original_path)
    best_data = b""
    best_size = (0, 0)
    best_quality = quality
    for width_cap in _width_steps(max(1, max_width)):
        fitted = _fit_width(rgb, width_cap)
        data, used_quality = _encode_under_budget(fitted, quality, target_bytes)
        best_data = data
        best_size = fitted.size
        best_quality = used_quality
        if len(data) <= target_bytes:
            break

    if not best_data:
        fitted = _fit_width(rgb, max(1, max_width))
        best_data = _encode_webp(fitted, max(MIN_QUALITY, quality))
        best_size = fitted.size
        best_quality = max(MIN_QUALITY, quality)

    return CompressedImage(
        data=best_data,
        width=best_size[0],
        height=best_size[1],
        quality=best_quality,
        original_bytes=original_bytes,
        original_path=path,
    )


def compress_to_webp(
    image_path: Path,
    *,
    max_width: int = MAX_WIDTH,
    quality: int = DEFAULT_QUALITY,
    target_bytes: int = TARGET_BYTES,
) -> CompressedImage:
    """Resize to ``max_width`` and encode WebP, stepping quality down toward ``target_bytes``."""
    path = Path(image_path)
    original_bytes = path.stat().st_size if path.exists() else 0
    with Image.open(path) as opened:
        return compress_image_to_webp(
            opened,
            path,
            original_bytes=original_bytes,
            max_width=max_width,
            quality=quality,
            target_bytes=target_bytes,
        )


def _width_steps(start: int) -> tuple[int, ...]:
    seen: list[int] = []
    current = start
    while current >= MIN_WIDTH:
        if current not in seen:
            seen.append(current)
        if current == MIN_WIDTH:
            break
        current = max(MIN_WIDTH, int(current * 0.75))
    if MIN_WIDTH not in seen:
        seen.append(MIN_WIDTH)
    return tuple(seen)


def _encode_under_budget(
    image: Image.Image, start_quality: int, target_bytes: int
) -> tuple[bytes, int]:
    """Binary-search quality so we hit the byte budget with few encodes."""
    high = max(MIN_QUALITY, min(100, start_quality))
    low = MIN_QUALITY
    first = _encode_webp(image, high)
    if len(first) <= target_bytes:
        return first, high
    best_under: bytes | None = None
    best_under_quality = high
    best_any = first
    best_any_quality = high
    while low <= high:
        mid = (low + high) // 2
        data = _encode_webp(image, mid)
        if len(data) <= target_bytes:
            best_under = data
            best_under_quality = mid
            low = mid + 1
        else:
            best_any = data
            best_any_quality = mid
            high = mid - 1
    if best_under is not None:
        return best_under, best_under_quality
    return best_any, best_any_quality
