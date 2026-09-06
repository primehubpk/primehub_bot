"""Pick which photos become catalog cards for each folder mode."""
from __future__ import annotations

from pathlib import Path

from rehan_bot.config import Settings

from .design_split import (
    collage_sources,
    existing_designs,
    last_written_designs,
    recheck_existing_designs,
    split_collages_in_folder,
    write_hero_cover,
)
from .folder_mode import (
    MODE_ALL_IN_ONE,
    MODE_EDIT_ONLY,
    MODE_EDIT_UPLOAD,
    MODE_ONE_PER_IMAGE,
    MODE_SPLIT_GROUP3,
    folder_mode,
    group_in_threes,
    is_cover_all,
    is_generated_design,
    is_one_pair_folder,
)
from .folder_parser import list_image_files


def list_sync_files(folder: Path) -> tuple[Path, ...]:
    """Images that decide skip/upload for this folder (design crops if present)."""
    mode = folder_mode(folder)
    if mode in {MODE_SPLIT_GROUP3, MODE_EDIT_ONLY, MODE_EDIT_UPLOAD}:
        designs = existing_designs(folder)
        cover = folder / "cover_all.webp"
        if cover.is_file():
            files = (cover, *designs) if designs else (cover,)
            return files
        sources = collage_sources(folder)
        if designs:
            return tuple(designs)
        if sources:
            return tuple(sources)
    return list_image_files(folder, limit=None)


def prepare_folder_files(folder: Path, settings: Settings | None) -> tuple[str, list[Path]]:
    """Split collages when needed, then return mode + files to publish."""
    mode = folder_mode(folder)
    if mode in {MODE_SPLIT_GROUP3, MODE_EDIT_ONLY, MODE_EDIT_UPLOAD}:
        recheck_existing_designs(folder, settings)
        split_collages_in_folder(folder, settings, dest=folder)
        batch = last_written_designs(folder)
        designs = batch or existing_designs(folder)
        sources = collage_sources(folder)
        if not designs:
            files = list(sources)
            if mode == MODE_EDIT_ONLY:
                return mode, files
            return MODE_ONE_PER_IMAGE, files
        cover = write_hero_cover(folder)
        files: list[Path] = []
        if cover is not None:
            files.append(cover)
        files.extend(designs)
        if mode == MODE_EDIT_ONLY:
            return mode, files
        if mode == MODE_EDIT_UPLOAD and not is_one_pair_folder(folder):
            return MODE_ONE_PER_IMAGE, designs or files
        return MODE_SPLIT_GROUP3, files
    return mode, list(list_image_files(folder, limit=None))


def product_groups(mode: str, files: list[Path]) -> list[list[Path]]:
    if mode == MODE_EDIT_ONLY:
        return []
    if mode == MODE_ALL_IN_ONE:
        return [list(files)] if files else []
    if mode == MODE_SPLIT_GROUP3:
        covers = [path for path in files if is_cover_all(path)]
        designs = [path for path in files if is_generated_design(path)]
        groups = group_in_threes(designs)
        if covers:
            hero = covers[0]
            return [[hero, *group] for group in groups]
        return groups
    if mode == MODE_ONE_PER_IMAGE:
        return [[path] for path in files]
    return [[path] for path in files]
