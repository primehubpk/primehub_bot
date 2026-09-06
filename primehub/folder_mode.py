"""Decide upload mode from a product folder name."""
from __future__ import annotations

import re
from pathlib import Path

MODE_ALL_IN_ONE = "all_in_one"
MODE_SPLIT_GROUP3 = "split_and_group3"
MODE_EDIT_ONLY = "edit_only"
MODE_EDIT_UPLOAD = "edit_upload"
MODE_ONE_PER_IMAGE = "one_per_image"

_SPACE = re.compile(r"[\s_\-]+")
DESIGN_PREFIX = "design_"
COVER_ALL_STEM = "cover_all"


def is_cover_all(path: Path | str) -> bool:
    return Path(path).stem.lower() == COVER_ALL_STEM


def _norm(name: str) -> str:
    return _SPACE.sub(" ", (name or "").lower()).strip()


def _compact(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def is_all_image_container(path: Path | str) -> bool:
    name = Path(path).name
    compact = _compact(name)
    return compact in {"allimage", "allimages"} or "all image" in _norm(name)


def is_edit_folder(path: Path | str) -> bool:
    name = Path(path).name
    return "edit folder" in _norm(name) or _compact(name) == "editfolder"


def is_edit_upload_folder(path: Path | str) -> bool:
    name = Path(path).name
    return "edit upload" in _norm(name) or _compact(name) == "editupload"


def is_one_pair_folder(path: Path | str) -> bool:
    """True when the folder name uses one / onepair / oneset / onepiece / onepack."""
    tokens = _norm(Path(path).name).split()
    for token in tokens:
        if token in {"only", "ones", "online"}:
            continue
        if token == "one" or token.startswith("one"):
            return True
    return False


def folder_needs_collage_edit(path: Path | str) -> bool:
    folder = Path(path)
    return (
        is_edit_folder(folder)
        or is_edit_upload_folder(folder)
        or is_one_pair_folder(folder)
    )


def folder_mode(path: Path | str) -> str:
    folder = Path(path)
    if is_edit_folder(folder):
        return MODE_EDIT_ONLY
    if is_all_image_container(folder) or is_all_image_container(folder.parent):
        return MODE_ALL_IN_ONE
    if is_edit_upload_folder(folder):
        return MODE_EDIT_UPLOAD
    if is_one_pair_folder(folder):
        return MODE_SPLIT_GROUP3
    return MODE_ONE_PER_IMAGE


def is_generated_design(path: Path) -> bool:
    stem = path.stem.lower()
    return stem.startswith(DESIGN_PREFIX) or stem.startswith("design-")


def group_in_threes(items: list) -> list[list]:
    return [items[index : index + 3] for index in range(0, len(items), 3)]
