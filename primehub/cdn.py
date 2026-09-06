"""Accepted storefront image hosts: new R2 URLs plus legacy ImgBB CDN links."""
from __future__ import annotations

from .imgbb import is_permanent_cdn_url

DEFAULT_R2_PUBLIC_BASE = "https://pub-157b90419bf04016bdea666e4cbce181.r2.dev"


def is_r2_public_url(url: str, public_base: str = "") -> bool:
    text = (url or "").strip()
    if not text.startswith("https://"):
        return False
    bases = [
        (public_base or "").rstrip("/"),
        DEFAULT_R2_PUBLIC_BASE,
    ]
    for base in bases:
        if base and text.startswith(base + "/"):
            return True
    return "://pub-" in text and text.split("/", 3)[2].endswith(".r2.dev")


def is_storefront_image_url(url: str, public_base: str = "") -> bool:
    """True for a new R2 object URL or an existing permanent ImgBB CDN file."""
    return is_r2_public_url(url, public_base) or is_permanent_cdn_url(url)
