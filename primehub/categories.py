"""Map a product folder onto a storefront category from the assets tree."""
from __future__ import annotations

from pathlib import Path

ASSETS_ROOT_NAME = "bangles assets"


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().replace("-", " ").replace("_", " ").split())


def assets_root(path: Path) -> Path | None:
    """Return the ``Bangles_Assets`` ancestor, if the path is under one."""
    for current in [Path(path), *Path(path).parents]:
        if _normalize(current.name) == ASSETS_ROOT_NAME:
            return current
    return None


def infer_assets_root(paths: list[Path] | tuple[Path, ...], configured: str = "") -> Path | None:
    configured_path = Path(configured) if str(configured or "").strip() else None
    if configured_path and configured_path.is_dir():
        return configured_path
    for path in paths:
        found = assets_root(path)
        if found is not None:
            return found
    return None


def preferred_category_from_text(text: str) -> str:
    """Leaf product names are not categories; path mapping owns that."""
    del text
    return ""


def wholesale_from_path(path: Path) -> bool:
    """True only when a path ancestor folder is named Wholesale."""
    return any(_normalize(part) == "wholesale" for part in Path(path).parts)


def looks_like_wholesale(text: str) -> bool:
    """Deprecated name: folder *names* like Dozen Box are not wholesale."""
    return _normalize(text) == "wholesale"


def match_category(
    hint: str,
    live_titles: list[str] | tuple[str, ...],
    default: str = "",
) -> str:
    """Prefer an exact live title (case-insensitive); otherwise keep the hint."""
    if not hint and default:
        hint = default
    if not hint:
        return ""
    normalized_hint = _normalize(hint)
    for title in live_titles:
        cleaned = str(title).strip()
        if cleaned and _normalize(cleaned) == normalized_hint:
            return cleaned
    return hint


def _parts_under_assets(folder: Path, root: Path) -> tuple[str, ...]:
    try:
        return Path(folder).resolve().relative_to(Path(root).resolve()).parts
    except (OSError, ValueError, RuntimeError):
        names = list(Path(folder).parts)
        for index, part in enumerate(names):
            if _normalize(part) == ASSETS_ROOT_NAME:
                return tuple(names[index + 1 :])
        return ()


def category_from_path(path: Path, default: str = "") -> str:
    """Use the top-level folder under ``Bangles_Assets`` as the category.

    ``Bangles_Assets/Ph Metal Deal/lot_price_999`` → ``Ph Metal Deal``.
    Nested material folders (``Glass Deal Box/Glass bangles/...``) do not win.
    """
    folder = Path(path)
    root = assets_root(folder)
    if root is not None:
        parts = _parts_under_assets(folder, root)
        if len(parts) >= 2:
            return parts[0]
        return default
    parent = folder.parent
    if parent.name and _normalize(parent.name) != ASSETS_ROOT_NAME:
        return parent.name
    return default
